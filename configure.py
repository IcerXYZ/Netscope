"""Create private environment files without executing their contents."""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import shlex
import tempfile
from werkzeug.security import generate_password_hash


def read_env(path):
    data={}
    if not path.exists(): return data
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        key, sep, raw=line.partition('=')
        if not sep or not key.startswith('NETSCOPE_'): raise ValueError('Invalid configuration line')
        parts=shlex.split(raw, comments=False)
        if len(parts)>1: raise ValueError('Quote configuration values')
        data[key]=parts[0] if parts else ''
    return data


def validate(data, docker=False):
    from security import Settings
    old=dict(os.environ)
    try:
        for key in list(os.environ):
            if key.startswith('NETSCOPE_'): del os.environ[key]
        os.environ.update(data)
        if docker:
            for key in ('NETSCOPE_TLS_CERT','NETSCOPE_TLS_KEY','NETSCOPE_CA_FILE'):
                value=os.environ.get(key,'')
                if value.startswith('/etc/netscope/'):
                    os.environ[key]=str(Path('runtime')/value.removeprefix('/etc/netscope/'))
        settings=Settings()
        if settings.tls:
            import ssl
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(settings.cert,settings.key)
        if os.environ.get('NETSCOPE_CA_FILE'):
            import ssl
            ssl.create_default_context(cafile=os.environ['NETSCOPE_CA_FILE'])
    finally:
        os.environ.clear(); os.environ.update(old)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--file',type=Path,default=Path('.env'))
    p.add_argument('--from-file',type=Path)
    p.add_argument('--check',action='store_true')
    p.add_argument('--docker',action='store_true')
    args=p.parse_args()
    data=read_env(args.from_file or args.file)
    if args.check:
        validate(data,args.docker); print('Configuration valid'); return
    def ask(label,key,default=''):
        old=data.get(key,default)
        value=input(f'{label} [{old}]: ').strip() or old
        data[key]=value
        return value
    role=ask('Role: single, server, or agent','NETSCOPE_ROLE','single')
    data['NETSCOPE_AUTH_ENABLED']='true'
    data['NETSCOPE_SECRET_KEY']=secrets.token_hex(32)
    data.pop('NETSCOPE_NODES',None)
    data.pop('NETSCOPE_HOST',None)
    ask('Specific bind IP (loopback by default)','NETSCOPE_BIND','127.0.0.1')
    ask('Port','NETSCOPE_PORT','8080')
    ask('Additional exact dashboard/agent-server DNS names, comma-separated','NETSCOPE_TRUSTED_HOSTS')
    from security import local_address
    if not local_address(data['NETSCOPE_BIND']):
        ask('TLS certificate file (include full chain)','NETSCOPE_TLS_CERT','/etc/netscope/tls.crt')
        ask('TLS private key file','NETSCOPE_TLS_KEY','/etc/netscope/tls.key')
    if role=='agent':
        data['NETSCOPE_BIND']='127.0.0.1'
        data['NETSCOPE_TLS_CERT']=''; data['NETSCOPE_TLS_KEY']=''
        ask('Central HTTPS URL','NETSCOPE_SERVER_URL')
        ask('Assigned agent ID','NETSCOPE_AGENT_ID')
        token=getpass.getpass('Agent token (blank preserves current): ')
        if token: data['NETSCOPE_AGENT_TOKEN']=token
        ask('Private CA certificate file (blank uses system trust)','NETSCOPE_CA_FILE')
    else:
        ask('Dashboard username','NETSCOPE_AUTH_USERNAME','admin')
        password=getpass.getpass('New dashboard password (blank preserves existing hash): ')
        if password:
            if len(password)<12 or len(password)>1024: p.error('Use 12-1024 characters')
            if password!=getpass.getpass('Confirm password: '): p.error('Passwords differ')
            data['NETSCOPE_AUTH_PASSWORD_HASH']=generate_password_hash(password,method='scrypt')
        for key in ('NETSCOPE_AGENT_TOKEN','NETSCOPE_SERVER_URL','NETSCOPE_AGENT_ID'):
            data.pop(key,None)
    data['NETSCOPE_AGENT_TOKENS_FILE']='/etc/netscope/agents.json'
    validate(data,args.docker)
    for value in data.values():
        if any(c in value for c in ('\n','\r','\x00',"'")): p.error('Unsupported configuration character')
    args.file.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=args.file.parent,prefix='.netscope-env-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            for key,value in sorted(data.items()): f.write(f"{key}='{value}'\n")
        os.chmod(tmp,0o600); os.replace(tmp,args.file)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    print('Saved private configuration. Restart/recreate NetScope to apply it.')


if __name__=='__main__': main()
