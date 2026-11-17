#!/usr/bin/env python3
"""NetScope: read-only Linux telemetry with central push-agent clustering."""
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
from datetime import timedelta
import os, platform, psutil, socket, time, json, threading, urllib.request, hmac, subprocess, re, collections
app=Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("NETSCOPE_SECRET_KEY") or os.urandom(32),
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=False, PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=1024 * 1024,
)
_login_attempts={}; _login_lock=threading.Lock(); _agent_report_times={}

def auth_enabled():
    return os.environ.get("NETSCOPE_AUTH_ENABLED","false").lower() in ("1","true","yes","on")

def dashboard_authenticated():
    return not auth_enabled() or bool(session.get("netscope_authenticated"))

@app.before_request
def protect_dashboard():
    if request.endpoint in ("login", "logout", "health", "agent_report") or request.path.startswith("/static/"):
        return None
    if dashboard_authenticated():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"error":"authentication required"}), 401
    return redirect(url_for("login", next=request.path))

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    response.headers["Cache-Control"]="no-store" if request.path.startswith("/api/") or request.path in ("/","/login") else response.headers.get("Cache-Control","")
    return response

@app.get("/login")
@app.post("/login")
def login():
    if not auth_enabled(): return redirect(url_for("index"))
    if request.method=="GET": return render_template("login.html", error="")
    ip=request.remote_addr or "unknown"; now=time.time()
    with _login_lock:
        attempts=[t for t in _login_attempts.get(ip,[]) if now-t<300]
        if len(attempts)>=5:
            _login_attempts[ip]=attempts
            return render_template("login.html", error="Too many attempts. Wait five minutes."), 429
        attempts.append(now); _login_attempts[ip]=attempts
    username=request.form.get("username","")[:128]
    password=request.form.get("password","")
    expected_user=os.environ.get("NETSCOPE_AUTH_USERNAME","")
    password_hash=os.environ.get("NETSCOPE_AUTH_PASSWORD_HASH","")
    if username==expected_user and password_hash and check_password_hash(password_hash,password):
        with _login_lock: _login_attempts.pop(ip,None)
        session.clear(); session["netscope_authenticated"]=True; session.permanent=True
        target=request.args.get("next","/")
        if not target.startswith("/") or target.startswith("//"): target="/"
        return redirect(target)
    return render_template("login.html", error="Incorrect username or password."), 401

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def load_agent_tokens():
    path=os.environ.get("NETSCOPE_AGENT_TOKENS_FILE","/etc/netscope-agent-tokens.json")
    try:
        with open(path,encoding="utf-8") as handle: value=json.load(handle)
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError): return {}

_previous={}; _previous_time=time.monotonic(); _alert_last={}; _alert_lock=threading.Lock()
_last_local_status=None; _status_snapshot_lock=threading.Lock()
_nodes={}; _nodes_lock=threading.Lock(); _agent_thread_started=False
_intel_cache={}; _intel_cache_time=0; _intel_lock=threading.Lock()

def notify_discord(key,message,cooldown=900):
    hook=os.environ.get("NETSCOPE_DISCORD_WEBHOOK","").strip()
    if not hook:return
    now=time.time()
    with _alert_lock:
        if now-_alert_last.get(key,0)<cooldown:return
        _alert_last[key]=now
    def send():
        try:
            body=json.dumps({"username":"NetScope","content":message[:1900]}).encode()
            req=urllib.request.Request(hook,data=body,headers={"Content-Type":"application/json"},method="POST")
            urllib.request.urlopen(req,timeout=4).read(64)
        except Exception as exc:app.logger.warning("Discord webhook failed: %s",exc)
    threading.Thread(target=send,daemon=True).start()


PORT_NAMES={22:"SSH",53:"DNS",80:"HTTP",123:"NTP",443:"HTTPS",445:"SMB",3306:"MySQL",3389:"RDP",5432:"PostgreSQL",5900:"VNC",8080:"HTTP-ALT",8443:"HTTPS-ALT",27015:"Game"}
def get_network_intelligence(force=False):
    """Read local socket metadata and SSH authentication failures; never capture payloads."""
    global _intel_cache,_intel_cache_time
    now=time.time()
    with _intel_lock:
        if not force and now-_intel_cache_time<8:return _intel_cache
    conns=[]; listeners=[]; port_counts=collections.Counter(); errors=[]
    try:
        for c in psutil.net_connections(kind="inet"):
            family="IPv6" if c.family==socket.AF_INET6 else "IPv4"
            proto="TCP" if c.type==socket.SOCK_STREAM else "UDP"
            local_ip=c.laddr.ip if c.laddr else ""; local_port=c.laddr.port if c.laddr else 0
            remote_ip=c.raddr.ip if c.raddr else ""; remote_port=c.raddr.port if c.raddr else 0
            state=c.status or ("BOUND" if local_port else "UNKNOWN")
            item={"protocol":proto,"family":family,"local_ip":local_ip,"local_port":local_port,"remote_ip":remote_ip,"remote_port":remote_port,"state":state,"pid":c.pid}
            if state=="LISTEN":
                listeners.append(item); port_counts[(proto,local_port)]+=1
            elif remote_ip:
                conns.append(item); port_counts[(proto,remote_port)]+=1
    except (psutil.AccessDenied,OSError) as exc:errors.append("Socket metadata unavailable: "+str(exc)[:120])
    conns.sort(key=lambda x:(x["state"]!="ESTABLISHED",x["remote_port"],x["remote_ip"]))
    listeners.sort(key=lambda x:(x["protocol"],x["local_port"]))
    frequent=[{"protocol":p,"port":port,"service":PORT_NAMES.get(port,"Unknown"),"observations":count} for (p,port),count in port_counts.most_common(20)]
    failed=[]; sources=[]
    commands=[["journalctl","-u","ssh.service","-u","sshd.service","--since","24 hours ago","--no-pager","-o","short-iso"]]
    for cmd in commands:
        try:
            completed=subprocess.run(cmd,capture_output=True,text=True,timeout=2,check=False)
            raw=completed.stdout
            if completed.returncode==0:sources.append("systemd journal")
            for line in raw.splitlines():
                if "Failed password" in line or "Invalid user" in line or "authentication failure" in line:
                    match=re.search(r"from ([0-9a-fA-F:.]+) port (\d+)",line)
                    user=re.search(r"(?:for invalid user|for) ([^ ]+)",line)
                    failed.append({"time":line[:25].strip(),"source_ip":match.group(1) if match else "Unknown","source_port":int(match.group(2)) if match else 0,"service":"SSH","target_port":22,"username":user.group(1) if user else "Unknown","event":"Invalid user" if "Invalid user" in line else "Failed authentication","message":line[:240]})
        except (FileNotFoundError,subprocess.TimeoutExpired):pass
    if not sources:
        root=os.environ.get("NETSCOPE_HOST_ROOT","/").rstrip("/")
        for path in (root+"/var/log/auth.log",root+"/var/log/secure"):
            try:
                with open(path,encoding="utf-8",errors="replace") as f: lines=f.readlines()[-5000:]
                sources.append(path)
                for line in lines:
                    if "Failed password" in line or "Invalid user" in line or "authentication failure" in line:
                        match=re.search(r"from ([0-9a-fA-F:.]+) port (\d+)",line)
                        user=re.search(r"(?:for invalid user|for) ([^ ]+)",line)
                        failed.append({"time":line[:15].strip(),"source_ip":match.group(1) if match else "Unknown","source_port":int(match.group(2)) if match else 0,"service":"SSH","target_port":22,"username":user.group(1) if user else "Unknown","event":"Invalid user" if "Invalid user" in line else "Failed authentication","message":line[-240:].strip()})
                break
            except OSError:continue
    failed=failed[-100:][::-1]
    result={"captured_at":int(now),"scope":"This machine's local sockets and SSH authentication log","connections":conns[:250],"connection_count":len(conns),"listeners":listeners[:150],"listener_count":len(listeners),"frequent_ports":frequent,"failed_logins":failed,"failed_login_count":len(failed),"log_sources":sources,"limitations":errors}
    with _intel_lock:_intel_cache=result;_intel_cache_time=now
    return result

def get_local_status():
    global _previous,_previous_time
    now=time.monotonic(); elapsed=max(now-_previous_time,.001)
    counters=psutil.net_io_counters(pernic=True); stats=psutil.net_if_stats(); addresses=psutil.net_if_addrs()
    interfaces=[]; next_previous={}
    for name,c in counters.items():
        old=_previous.get(name); rx=max(0,(c.bytes_recv-old[0])/elapsed) if old else 0; tx=max(0,(c.bytes_sent-old[1])/elapsed) if old else 0
        next_previous[name]=(c.bytes_recv,c.bytes_sent); st=stats.get(name)
        ip=next((x.address for x in addresses.get(name,[]) if x.family==socket.AF_INET),"")
        interfaces.append({"name":name,"ipv4":ip,"is_up":bool(st and st.isup),"speed_mbps":st.speed if st else 0,"mtu":st.mtu if st else 0,"rx_rate":rx,"tx_rate":tx,"rx_total":c.bytes_recv,"tx_total":c.bytes_sent,"packets_recv":c.packets_recv,"packets_sent":c.packets_sent,"errors_in":c.errin,"errors_out":c.errout,"drops_in":c.dropin,"drops_out":c.dropout})
    _previous,_previous_time=next_previous,now
    mem,swap,disk=psutil.virtual_memory(),psutil.swap_memory(),psutil.disk_usage(os.environ.get("NETSCOPE_HOST_ROOT","/"))
    freq=psutil.cpu_freq(); load=os.getloadavg() if hasattr(os,"getloadavg") else [0,0,0]
    processes=[]
    for p in psutil.process_iter(["pid","name","username","memory_percent"]):
        try:
            x=p.info; processes.append({"pid":x.get("pid"),"name":x.get("name") or "unknown","user":x.get("username") or "","memory_percent":round(x.get("memory_percent") or 0,2)})
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    data={"timestamp":int(time.time()),"hostname":socket.gethostname(),"fqdn":socket.getfqdn(),"primary_ip":next((i["ipv4"] for i in interfaces if i["ipv4"] and i["name"]!="lo"),""),"os":platform.platform(),"kernel":platform.release(),"cpu_percent":psutil.cpu_percent(interval=None),"cpu_count":psutil.cpu_count(logical=True) or 0,"cpu_physical":psutil.cpu_count(logical=False) or 0,"cpu_frequency_mhz":freq.current if freq else 0,"load_1":load[0],"load_5":load[1],"load_15":load[2],"memory_percent":mem.percent,"memory_used":mem.used,"memory_total":mem.total,"memory_available":mem.available,"swap_percent":swap.percent,"swap_used":swap.used,"swap_total":swap.total,"disk_percent":disk.percent,"disk_used":disk.used,"disk_total":disk.total,"disk_free":disk.free,"uptime":int(time.time()-psutil.boot_time()),"interfaces":interfaces,"processes":sorted(processes,key=lambda x:x["memory_percent"],reverse=True)[:8],"network_intel":get_network_intelligence()}
    for metric,value in (("CPU",data["cpu_percent"]),("RAM",data["memory_percent"]),("Disk",data["disk_percent"])):
        if value>=90:notify_discord(socket.gethostname()+":"+metric,f"⚠️ **NetScope alert — {socket.gethostname()}**\n{metric} usage is {value:.1f}% (90% threshold).")
    return data

def nodes_config():
    try:
        value=json.loads(os.environ.get("NETSCOPE_NODES","[]"))
        return [{"name":str(n["name"]),"url":str(n["url"]).rstrip("/")} for n in value if n.get("name") and n.get("url")]
    except (ValueError,TypeError,KeyError):
        app.logger.warning("Invalid NETSCOPE_NODES JSON."); return []

def agent_sender():
    server=os.environ.get("NETSCOPE_SERVER_URL","").strip().rstrip("/")
    token=os.environ.get("NETSCOPE_AGENT_TOKEN","").strip()
    agent_id=os.environ.get("NETSCOPE_AGENT_ID","").strip()
    if not server or not token or not agent_id:
        app.logger.error("Agent mode needs NETSCOPE_SERVER_URL, NETSCOPE_AGENT_ID and NETSCOPE_AGENT_TOKEN."); return
    while True:
        try:
            data=get_local_status()
            payload=json.dumps({"name":socket.gethostname(),"agent_id":agent_id,"data":data}).encode()
            req=urllib.request.Request(server+"/api/agent/report",data=payload,headers={"Content-Type":"application/json","X-NetScope-Token":token,"User-Agent":"NetScope-Agent/2"},method="POST")
            with urllib.request.urlopen(req,timeout=5) as response:response.read(256)
        except Exception as exc:app.logger.warning("Could not report to central server %s: %s",server,exc)
        time.sleep(5)

def start_agent_sender():
    global _agent_thread_started
    if os.environ.get("NETSCOPE_ROLE","single").lower()!="agent" or _agent_thread_started:return
    _agent_thread_started=True
    threading.Thread(target=agent_sender,name="netscope-agent-reporter",daemon=True).start()

@app.get("/")
def index():return render_template("index.html", auth_enabled=auth_enabled())
@app.get("/api/status")
def status():
    global _last_local_status
    try:
        data=get_local_status()
        with _status_snapshot_lock: _last_local_status=data
        return jsonify(data)
    except Exception as exc:
        app.logger.exception("Telemetry collection failed")
        return jsonify({"error":"Telemetry collection failed: "+str(exc)[:180]}),503

@app.post("/api/agent/report")
def agent_report():
    body=request.get_json(silent=True)
    if not isinstance(body,dict): return jsonify({"error":"invalid JSON report"}),400
    agent_id=str(body.get("agent_id","")).strip()
    name=str(body.get("name","")).strip()
    data=body.get("data")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",agent_id) or not name or len(name)>80 or not isinstance(data,dict) or not isinstance(data.get("hostname"),str):
        return jsonify({"error":"invalid report"}),400
    token_hash=load_agent_tokens().get(agent_id)
    supplied=request.headers.get("X-NetScope-Token","")
    now_rate=time.time()
    if not isinstance(token_hash,str) or not supplied or not check_password_hash(token_hash,supplied):
        return jsonify({"error":"unauthorized"}),401
    with _nodes_lock:
        recent=[stamp for stamp in _agent_report_times.get(agent_id,[]) if now_rate-stamp<60]
        if len(recent)>=30: return jsonify({"error":"rate limit exceeded"}),429
        recent.append(now_rate); _agent_report_times[agent_id]=recent
    now=int(time.time())
    with _nodes_lock:_nodes[agent_id]={"name":name,"agent_id":agent_id,"online":True,"last_seen":now,"data":data,"error":""}
    return jsonify({"accepted":True,"received_at":now})

@app.get("/api/network-intel")
def network_intel():
    try:
        return jsonify(get_network_intelligence(force=True))
    except Exception as exc:
        app.logger.exception("Network intelligence collection failed")
        return jsonify({"error":"Network intelligence unavailable: "+str(exc)[:160]}),503

@app.get("/api/cluster")
def cluster():
    role=os.environ.get("NETSCOPE_ROLE","single").lower(); result=[]
    if role!="agent":
        with _status_snapshot_lock: local=_last_local_status
        if local is None: local=get_local_status()
        result.append({"name":local["hostname"],"url":"local","online":True,"last_seen":int(time.time()),"data":local,"kind":"central"})
    now=int(time.time())
    with _nodes_lock:reports=list(_nodes.values())
    for node in reports:
        online=now-node["last_seen"]<=25
        result.append({**node,"online":online,"kind":"agent","error":"" if online else "No heartbeat received for 25 seconds"})
        if not online:notify_discord("agent-offline:"+node["agent_id"],f"🔴 **NetScope — agent offline**\n{node['name']} has stopped reporting to the central server.")
    for node in nodes_config():
        try:
            req=urllib.request.Request(node["url"]+"/api/status",headers={"User-Agent":"NetScope"})
            with urllib.request.urlopen(req,timeout=2) as response:data=json.loads(response.read(2000000))
            result.append({"name":node["name"],"url":node["url"],"online":True,"last_seen":now,"data":data,"kind":"polling"})
        except Exception as exc:result.append({"name":node["name"],"url":node["url"],"online":False,"last_seen":0,"error":str(exc)[:140],"data":None,"kind":"polling"})
    return jsonify({"mode":"cluster","nodes":result,"online":sum(1 for n in result if n["online"]),"total":len(result)})

@app.get("/health")
def health():return jsonify({"status":"ok","service":"netscope"})

start_agent_sender()
