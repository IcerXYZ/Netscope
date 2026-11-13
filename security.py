"""Strict deployment settings and bounded, single-worker security state."""
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import threading
import time
from collections import OrderedDict, deque
from urllib.parse import urlsplit
import urllib.request


def local_address(value):
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == 'localhost'


def validate_url(value, loopback_http=False):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' and not (loopback_http and parsed.scheme == 'http' and local_address(parsed.hostname or ''))):
        raise ValueError('Use HTTPS with a trusted certificate for network connections')
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('Invalid service URL')
    _ = parsed.port
    return value.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'Redirect refused', headers, fp)


def secure_opener():
    import ssl
    context = ssl.create_default_context(cafile=os.environ.get('NETSCOPE_CA_FILE') or None)
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), urllib.request.HTTPSHandler(context=context))


class Settings:
    def __init__(self):
        self.role = os.environ.get('NETSCOPE_ROLE', 'single')
        if self.role not in ('single', 'server', 'agent'):
            raise ValueError('Invalid NETSCOPE_ROLE')
        self.bind = os.environ.get('NETSCOPE_BIND', '127.0.0.1')
        address = ipaddress.ip_address(self.bind)
        if address.version != 4:
            raise ValueError('This release supports explicit IPv4 listener addresses')
        if address.is_unspecified or address.is_multicast or not address.is_private:
            raise ValueError('Bind to a specific private or loopback address')
        self.port = int(os.environ.get('NETSCOPE_PORT', '8080'))
        if not 1024 <= self.port <= 65535:
            raise ValueError('NETSCOPE_PORT must be between 1024 and 65535')
        if self.role == 'agent' and not address.is_loopback:
            raise ValueError('Agent listener must remain on loopback')
        self.cert = os.environ.get('NETSCOPE_TLS_CERT', '')
        self.key = os.environ.get('NETSCOPE_TLS_KEY', '')
        if bool(self.cert) != bool(self.key):
            raise ValueError('Both TLS certificate and key are required')
        self.tls = bool(self.cert)
        if not address.is_loopback and not self.tls:
            raise ValueError('LAN access requires TLS certificate and key')
        for path in (self.cert, self.key):
            if path and not os.path.isfile(path):
                raise ValueError('TLS file does not exist')
        if os.environ.get('NETSCOPE_AUTH_ENABLED', 'true').lower() not in ('true', '1', 'yes', 'on'):
            raise ValueError('Dashboard authentication cannot be disabled')
        self.secret = os.environ.get('NETSCOPE_SECRET_KEY', '')
        if not re.fullmatch(r'[0-9a-fA-F]{64,128}', self.secret) or len(set(self.secret.lower())) < 12:
            raise ValueError('Generate NETSCOPE_SECRET_KEY using secrets.token_hex(32)')
        self.username = os.environ.get('NETSCOPE_AUTH_USERNAME', '')
        self.password_hash = os.environ.get('NETSCOPE_AUTH_PASSWORD_HASH', '')
        if self.role != 'agent':
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', self.username):
                raise ValueError('Configure a dashboard username')
            if not re.fullmatch(r'scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[a-f0-9]{128}', self.password_hash):
                raise ValueError('Configure a scrypt dashboard password hash')
        self.hosts = ['localhost', '127.0.0.1', self.bind]
        for host in os.environ.get('NETSCOPE_TRUSTED_HOSTS', '').split(','):
            host = host.strip().lower()
            if not host:
                continue
            if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host) or '..' in host:
                raise ValueError('Trusted hosts must be exact names, without ports or wildcards')
            self.hosts.append(host)
        if os.environ.get('NETSCOPE_NODES') not in (None, '', '[]'):
            raise ValueError('Legacy polling is removed; enroll authenticated push agents')
        if self.role == 'agent':
            validate_url(os.environ.get('NETSCOPE_SERVER_URL', ''))
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', os.environ.get('NETSCOPE_AGENT_ID', '')):
                raise ValueError('Configure an agent ID')
            if not re.fullmatch(r'[A-Za-z0-9_-]{48}', os.environ.get('NETSCOPE_AGENT_TOKEN', '')):
                raise ValueError('Enroll a new individual agent token')
        hook = os.environ.get('NETSCOPE_DISCORD_WEBHOOK', '')
        if hook:
            validate_url(hook)
            parsed = urlsplit(hook)
            if parsed.hostname != 'discord.com' or parsed.port not in (None, 443) or not parsed.path.startswith('/api/webhooks/'):
                raise ValueError('Use a Discord HTTPS webhook URL')


class Limiter:
    def __init__(self, capacity=4096):
        self.entries = OrderedDict()
        self.lock = threading.Lock()
        self.capacity = capacity

    def allow(self, key, count, window):
        now = time.monotonic()
        with self.lock:
            for old in list(self.entries):
                if self.entries[old][1] <= now:
                    del self.entries[old]
            if key not in self.entries:
                if len(self.entries) >= self.capacity:
                    return False
                self.entries[key] = (deque(), now + window)
            times, _ = self.entries[key]
            while times and times[0] <= now - window:
                times.popleft()
            if len(times) >= count:
                return False
            times.append(now)
            self.entries[key] = (times, now + window)
            return True


class Sessions:
    def __init__(self):
        self.entries = {}
        self.lock = threading.Lock()

    def fingerprint(self):
        return hashlib.sha256((os.environ.get('NETSCOPE_AUTH_USERNAME', '') + '\0' + os.environ.get('NETSCOPE_AUTH_PASSWORD_HASH', '')).encode()).hexdigest()

    def create(self):
        now = time.time()
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if v[0] > now}
            if len(self.entries) >= 256:
                return None
            sid = secrets.token_urlsafe(32)
            self.entries[sid] = (now + 8 * 3600, self.fingerprint())
            return sid

    def valid(self, sid):
        if not isinstance(sid, str):
            return False
        with self.lock:
            record = self.entries.get(sid)
            if not record:
                return False
            if record[0] <= time.time() or not hmac.compare_digest(record[1], self.fingerprint()):
                self.entries.pop(sid, None)
                return False
            return True

    def revoke(self, sid):
        with self.lock:
            self.entries.pop(sid, None)


def token_matches(stored, supplied):
    if not isinstance(stored, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', stored):
        return False
    if not re.fullmatch(r'[A-Za-z0-9_-]{48}', supplied):
        return False
    return hmac.compare_digest(stored[7:], hashlib.sha256(supplied.encode()).hexdigest())
