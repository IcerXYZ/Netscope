"""Real Gunicorn/TLS login, telemetry and cookie-revocation checks on CI."""
import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

base='https://localhost:18080'
try:
    urllib.request.urlopen(base+'/health',timeout=5)
except urllib.error.URLError:
    pass
else:
    raise AssertionError('Untrusted test certificate unexpectedly accepted')
context=ssl.create_default_context(cafile='/etc/netscope/tls.crt')
cookies=http.cookiejar.CookieJar()
client=urllib.request.build_opener(urllib.request.HTTPSHandler(context=context),urllib.request.HTTPCookieProcessor(cookies))
with client.open(base+'/login',timeout=5) as response:
    html=response.read().decode()
    assert 'Secure' in response.headers['Set-Cookie']
token=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
form=urllib.parse.urlencode({'csrf_token':token,'username':'admin','password':'integration-test-password'}).encode()
with client.open(base+'/login',data=form,timeout=5) as response:
    assert response.status==200
    html=response.read().decode()
captured=next(c.value for c in cookies if c.name=='session')
with client.open(base+'/api/status',timeout=10) as response:
    data=json.load(response)
    assert isinstance(data['interfaces'],list)
    from telemetry_schema import validate
    validate(data)
token=re.search(r'name="csrf_token" value="([^"]+)"',html).group(1)
with client.open(base+'/logout',data=urllib.parse.urlencode({'csrf_token':token}).encode(),timeout=5) as response:
    assert response.status==200
request=urllib.request.Request(base+'/api/status',headers={'Cookie':'session='+captured})
try:
    urllib.request.urlopen(request,context=context,timeout=5)
except urllib.error.HTTPError as error:
    assert error.code==401
    error.close()
else:
    raise AssertionError('Logged-out cookie replay accepted')
print('Real TLS trust, login, telemetry schema and logout replay checks passed.')
