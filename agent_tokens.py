#!/opt/netscope/venv/bin/python
import argparse, grp, json, os, secrets, sys, tempfile
from werkzeug.security import generate_password_hash
PATH="/etc/netscope-agent-tokens.json"
def read():
    try:
        with open(PATH, encoding="utf-8") as f: return json.load(f)
    except FileNotFoundError: return {}
def write(data):
    fd,tmp=tempfile.mkstemp(dir=os.path.dirname(PATH),prefix=".netscope-tokens-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(data,f,indent=2); f.write("\n")
        os.chown(tmp,0,grp.getgrnam("netscope").gr_gid); os.chmod(tmp,0o640); os.replace(tmp,PATH)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
p=argparse.ArgumentParser(description="Manage individual NetScope agent credentials")
p.add_argument("action",choices=["add","revoke","list"])
p.add_argument("agent_id",nargs="?")
a=p.parse_args()
data=read()
if a.action=="list":
    for key in sorted(data): print(key)
elif not a.agent_id or len(a.agent_id)>64 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in a.agent_id):
    p.error("agent_id must contain only letters, numbers, dot, underscore or dash (max 64)")
elif a.action=="add":
    token=secrets.token_urlsafe(36); data[a.agent_id]=generate_password_hash(token,method="scrypt"); write(data)
    print("Agent ID: "+a.agent_id); print("Agent token (shown once): "+token)
elif a.action=="revoke":
    if a.agent_id not in data: sys.exit("Unknown agent ID")
    del data[a.agent_id]; write(data); print("Revoked: "+a.agent_id)
