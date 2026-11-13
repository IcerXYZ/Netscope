#!/usr/bin/env python3
"""Host-side, locked and atomic token administration."""
import argparse, hashlib, json, os, re, secrets, tempfile
from pathlib import Path
from filelock import FileLock

def read(path):
    try: raw=path.read_text(encoding="utf-8")
    except FileNotFoundError: return {}
    data=json.loads(raw) if raw.strip() else {}
    if not isinstance(data,dict): raise ValueError("Invalid token registry")
    return data

def write(path,data,group_id=None):
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".agents-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.chmod(name,0o640)
        if os.name=="posix":
            import grp
            try: gid=grp.getgrnam("netscope").gr_gid
            except KeyError: gid=os.getgid()
            if group_id is not None: gid=group_id
            os.chown(name,0,gid)
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def main():
    p=argparse.ArgumentParser(description="Manage unique NetScope agent credentials")
    p.add_argument("action",choices=["add","revoke","list"])
    p.add_argument("agent_id",nargs="?")
    p.add_argument("--file",type=Path,default=Path("/etc/netscope/agents.json"))
    p.add_argument("--group-id",type=int,help="Registry reader group ID (10001 for Docker)")
    a=p.parse_args()
    if os.name=="posix" and os.geteuid()!=0: p.error("Run as root")
    if a.action!="list" and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",a.agent_id or ""): p.error("Invalid agent ID")
    os.umask(0o077); a.file.parent.mkdir(mode=0o750,parents=True,exist_ok=True)
    with FileLock(str(a.file)+".lock",timeout=10):
        data=read(a.file)
        if a.action=="list":
            for key in sorted(data): print(key)
        elif a.action=="add":
            if a.agent_id not in data and len(data)>=256: p.error("At most 256 agents supported")
            token=secrets.token_urlsafe(36)
            data[a.agent_id]="sha256:"+hashlib.sha256(token.encode()).hexdigest()
            write(a.file,data,a.group_id)
            print("Agent ID: "+a.agent_id); print("Token (shown once): "+token)
        else:
            if a.agent_id not in data: p.error("Unknown agent ID")
            del data[a.agent_id]; write(a.file,data,a.group_id); print("Revoked: "+a.agent_id)

if __name__=="__main__": main()

