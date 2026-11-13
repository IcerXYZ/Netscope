import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from werkzeug.security import generate_password_hash

PASSWORD=generate_password_hash('test-dashboard-password',method='scrypt')
os.environ.update(NETSCOPE_SECRET_KEY=secrets.token_hex(32), NETSCOPE_ROLE='server', NETSCOPE_BIND='127.0.0.1',
    NETSCOPE_AUTH_ENABLED='true',NETSCOPE_AUTH_USERNAME='admin',NETSCOPE_AUTH_PASSWORD_HASH=PASSWORD)
import app as ns
from security import Settings, Limiter, Sessions, NoRedirect
from telemetry_schema import validate
from agent_tokens import read, write
from configure import read_env


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.registry=Path(self.temp.name)/'agents.json'
        self.token=secrets.token_urlsafe(36)
        self.registry.write_text(json.dumps({'node-01':'sha256:'+hashlib.sha256(self.token.encode()).hexdigest()}))
        self.env=patch.dict(os.environ,NETSCOPE_AGENT_TOKENS_FILE=str(self.registry),NETSCOPE_AUTH_PASSWORD_HASH=PASSWORD)
        self.env.start()
        ns.app.config.update(TESTING=True,SECRET_KEY=secrets.token_hex(32),SESSION_COOKIE_SECURE=False)
        ns.limiter=Limiter(); ns.sessions=Sessions(); ns._nodes.clear()
        self.status=patch.object(ns,'get_local_status',return_value={'hostname':'synthetic-host'})
        self.intel=patch.object(ns,'get_network_intelligence',return_value={'connections':[]})
        self.status.start(); self.intel.start()
        self.client=ns.app.test_client()

    def tearDown(self):
        self.env.stop(); self.status.stop(); self.intel.stop(); self.temp.cleanup()

    def csrf(self):
        self.client.get('/login')
        with self.client.session_transaction() as sess: return sess['csrf']

    def login(self,password='test-dashboard-password',headers=None):
        token=self.csrf()
        return self.client.post('/login',data={'username':'admin','password':password,'csrf_token':token},headers=headers or {})

    def report(self,data=None,token=None):
        return self.client.post('/api/agent/report',json={'agent_id':'node-01','name':'spoofed-central','data':data or {'hostname':'node'}},headers={'X-NetScope-Token':self.token if token is None else token})

    def test_apis_require_login(self):
        for path in ['/api/status','/api/cluster','/api/network-intel']:
            self.assertEqual(self.client.get(path).status_code,401)

    def test_auth_settings_cannot_disable_login(self):
        for value in ['false','tru','0','']:
            with patch.dict(os.environ,NETSCOPE_AUTH_ENABLED=value):
                with self.assertRaises(ValueError): Settings()

    def test_missing_credentials_fail_startup(self):
        with patch.dict(os.environ,NETSCOPE_AUTH_PASSWORD_HASH=''):
            with self.assertRaises(ValueError): Settings()

    def test_placeholder_secret_rejected(self):
        for value in ['replace-with-a-long-random-secret','a'*64,'']:
            with patch.dict(os.environ,NETSCOPE_SECRET_KEY=value):
                with self.assertRaises(ValueError): Settings()

    def test_cookie_claim_without_server_session_rejected(self):
        with self.client.session_transaction() as sess: sess['netscope_authenticated']=True; sess['sid']='invented'
        self.assertEqual(self.client.get('/api/status').status_code,401)

    def test_unknown_host_rejected(self):
        self.assertEqual(self.client.get('/api/status',headers={'Host':'attacker.invalid'}).status_code,400)

    def test_wildcard_host_configuration_rejected(self):
        with patch.dict(os.environ,NETSCOPE_TRUSTED_HOSTS='.example.com'):
            with self.assertRaises(ValueError): Settings()

    def test_lan_requires_tls(self):
        with patch.dict(os.environ,NETSCOPE_BIND='192.168.1.10',NETSCOPE_TLS_CERT='',NETSCOPE_TLS_KEY=''):
            with self.assertRaises(ValueError): Settings()

    def test_all_interface_and_public_bind_rejected(self):
        for address in ['0.0.0.0','::','8.8.8.8']:
            with patch.dict(os.environ,NETSCOPE_BIND=address):
                with self.assertRaises(ValueError): Settings()

    def test_valid_login_and_headers(self):
        self.assertEqual(self.login().status_code,302)
        r=self.client.get('/api/status')
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(r.headers['X-Frame-Options'],'DENY')
        self.assertIn('Content-Security-Policy',r.headers)

    def test_csrf_and_foreign_origin_rejected(self):
        self.assertEqual(self.client.post('/login',data={'username':'admin','password':'test-dashboard-password'}).status_code,403)
        self.assertEqual(self.login(headers={'Origin':'https://attacker.invalid'}).status_code,403)

    def test_unicode_csrf_rejected_without_server_error(self):
        self.csrf()
        self.assertEqual(self.client.post('/login',data={'csrf_token':'\u2603'}).status_code,403)

    def test_login_throttling(self):
        for _ in range(5): self.assertEqual(self.login('wrong').status_code,401)
        self.assertEqual(self.login().status_code,429)

    def test_logout_revokes_captured_cookie(self):
        self.login(); cookie=self.client.get_cookie('session').value
        with self.client.session_transaction() as sess: token=sess['csrf']
        self.assertEqual(self.client.post('/logout',data={'csrf_token':token}).status_code,302)
        attacker=ns.app.test_client(); attacker.set_cookie('session',cookie)
        self.assertEqual(attacker.get('/api/status').status_code,401)

    def test_password_change_revokes_session(self):
        self.login()
        with patch.dict(os.environ,NETSCOPE_AUTH_PASSWORD_HASH='changed'):
            self.assertEqual(self.client.get('/api/status').status_code,401)

    def test_absolute_session_expiry(self):
        origin=time.time()
        with patch('time.time',return_value=origin): self.login()
        with patch('time.time',return_value=origin+7*3600): self.assertEqual(self.client.get('/api/status').status_code,200)
        with patch('time.time',return_value=origin+9*3600): self.assertEqual(self.client.get('/api/status').status_code,401)

    def test_tls_requires_secure_transport_and_cookie(self):
        with patch.object(ns.settings,'tls',True):
            ns.app.config['SESSION_COOKIE_SECURE']=True
            self.assertEqual(self.client.get('/health').status_code,400)
            r=self.client.get('/login',base_url='https://localhost')
            self.assertIn('; Secure',r.headers['Set-Cookie'])
            self.assertIn('Strict-Transport-Security',r.headers)

    def test_agent_and_dashboard_credentials_separate(self):
        self.assertEqual(self.client.get('/api/status',headers={'X-NetScope-Token':self.token}).status_code,401)
        self.login(); self.assertEqual(self.report(token='').status_code,401)

    def test_report_auth_and_revocation(self):
        self.assertEqual(self.report(token='wrong').status_code,401)
        self.assertEqual(self.report().status_code,200)
        self.registry.write_text('{}')
        self.assertEqual(self.report().status_code,401)
        self.login(); self.assertEqual(len(self.client.get('/api/cluster').json['nodes']),1)

    def test_agent_identity_is_bound_to_credential(self):
        self.report(); self.assertEqual(ns._nodes['node-01']['name'],'node-01')

    def test_bad_report_schema_rejected(self):
        for data in [{'hostname':'node','interfaces':'bad'},{'hostname':'node','cpu_percent':float('nan')},
                     {'hostname':'node','network_intel':{'connections':42}}, {'hostname':'node','cpu_percent':float('inf')},
                     {'hostname':'node','interfaces':[{}]*65}, {'hostname':'node','extra':'unknown'}]:
            self.assertEqual(self.report(data).status_code,400)

    def test_full_schema_accepts_valid_report(self):
        data={'hostname':'node','interfaces':[{'name':'eth0','is_up':True,'rx_rate':0,'ipv4':'192.168.1.5'}],
              'network_intel':{'connections':[{'pid':None,'local_port':443,'protocol':'TCP'}], 'limitations':[]}}
        self.assertEqual(self.report(data).status_code,200)

    def test_bad_tokens_throttled_before_verification(self):
        with patch.object(ns,'token_matches',return_value=False) as verify:
            for _ in range(30): self.assertEqual(self.report(token='wrong').status_code,401)
            self.assertEqual(self.report(token='wrong').status_code,429)
            self.assertEqual(verify.call_count,30)

    def test_stale_reports_purged(self):
        self.report(); ns._nodes['node-01']['last_seen']=1
        self.login(); self.client.get('/api/cluster')
        self.assertNotIn('node-01',ns._nodes)

    def test_report_size_and_invalid_json(self):
        self.assertEqual(self.report({'hostname':'node','pad':'x'*262144}).status_code,413)
        for data in ['null','[]','{broken','['*1100+'0'+']'*1100]:
            self.assertEqual(self.client.post('/api/agent/report',data=data,content_type='application/json').status_code,400)

    def test_redirects_never_forward_tokens(self):
        req=urllib.request.Request('https://central.invalid/api/agent/report',data=b'{}',headers={'X-NetScope-Token':self.token})
        for url in ['http://other.invalid/','https://other.invalid/','https://central.invalid/other']:
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                NoRedirect().redirect_request(req,None,302,'Found',{},url)
            rejected.exception.close()

    def test_error_details_hidden(self):
        self.login()
        with patch.object(ns,'get_local_status',side_effect=OSError('private-path')):
            with self.assertLogs(ns.app.logger,level='ERROR'):
                r=self.client.get('/api/status')
        self.assertEqual(r.status_code,503); self.assertNotIn('private-path',r.get_data(as_text=True))

    def test_registry_initialization_and_atomic_replace(self):
        self.registry.write_text(''); self.assertEqual(read(self.registry),{})
        with patch('os.chown',create=True): write(self.registry,{'node-02':'digest'})
        self.assertEqual(read(self.registry),{'node-02':'digest'})

    def test_no_permissive_cors_and_no_static_traversal(self):
        self.assertNotIn('Access-Control-Allow-Origin',self.client.get('/health',headers={'Origin':'https://evil.invalid'}).headers)
        self.assertEqual(self.client.get('/static/../app.py').status_code,404)

    def test_limiter_storage_is_bounded_and_expires(self):
        limiter=Limiter(capacity=2)
        self.assertTrue(limiter.allow('a',1,60)); self.assertTrue(limiter.allow('b',1,60))
        self.assertFalse(limiter.allow('c',1,60))
        with patch('time.monotonic',return_value=time.monotonic()+61): self.assertTrue(limiter.allow('c',1,60))

    def test_configuration_read_is_data_not_shell(self):
        path=Path(self.temp.name)/'env'
        path.write_text("NETSCOPE_AUTH_PASSWORD_HASH='scrypt:32768:8:1$abc$def'\n")
        self.assertEqual(read_env(path)['NETSCOPE_AUTH_PASSWORD_HASH'],'scrypt:32768:8:1$abc$def')

    def test_large_logs_are_read_with_a_byte_limit(self):
        self.intel.stop()
        log=Path(self.temp.name)/'var/log/auth.log'
        log.parent.mkdir(parents=True)
        log.write_text(('Jan 1 sshd: Failed password for user from 192.168.1.3 port 12345 ssh2\n')*12000)
        reads=[]
        original_open=open
        class Tracked:
            def __init__(self,*args,**kwargs): self.file=original_open(*args,**kwargs)
            def __enter__(self): return self
            def __exit__(self,*args): self.file.close()
            def seek(self,*args): return self.file.seek(*args)
            def tell(self): return self.file.tell()
            def read(self,size=-1): reads.append(size); return self.file.read(size)
        with patch.dict(os.environ,NETSCOPE_HOST_ROOT=self.temp.name), \
             patch.object(ns.psutil,'net_connections',return_value=[]), \
             patch.object(ns.subprocess,'run',side_effect=FileNotFoundError), \
             patch('builtins.open',Tracked):
            result=ns.get_network_intelligence(force=True)
        self.assertEqual(reads,[512*1024])
        self.assertEqual(len(result['failed_logins']),100)

    def test_local_telemetry_is_normalized_before_reporting(self):
        from telemetry_schema import sanitize_local
        data=sanitize_local({'hostname':'node','interfaces':[{'name':'eth\t0','speed_mbps':-1}]*80,'cpu_percent':float('nan')})
        validate(data)
        self.assertEqual(len(data['interfaces']),64)
        self.assertEqual(data['interfaces'][0]['name'],'eth 0')
        self.assertEqual(data['cpu_percent'],0)


if __name__=='__main__': unittest.main()
