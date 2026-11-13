import ssl
from security import Settings
settings=Settings()
workers=1
worker_class="sync"
bind=("["+settings.bind+"]" if ":" in settings.bind else settings.bind)+":"+str(settings.port)
certfile=settings.cert or None
keyfile=settings.key or None
accesslog=None
errorlog="-"
timeout=30
limit_request_line=2048
limit_request_fields=30
limit_request_field_size=4096
forwarded_allow_ips=""
secure_scheme_headers={}
def ssl_context(conf,default_ssl_context_factory):
    context=default_ssl_context_factory()
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    return context

