"""Validated service entry point; no shell interpolation."""
import os, ssl, sys
from pathlib import Path
from security import Settings
if __name__=="__main__":
    config=Settings(); root=Path(__file__).resolve().parent
    if config.role=="agent":
        os.execv(sys.executable,[sys.executable,str(root/"app.py")])
    if config.tls:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(config.cert,config.key)
    os.execv(sys.executable,[sys.executable,"-m","gunicorn","--config",str(root/"gunicorn.conf.py"),"app:app"])

