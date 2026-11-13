#!/usr/bin/env python3
"""NetScope: read-only Linux telemetry with central push-agent clustering."""
from flask import Flask, jsonify, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
from datetime import timedelta
import os, platform, psutil, socket, time, json, threading, urllib.request, hmac, subprocess, re, collections
from security import Settings, Limiter, Sessions, secure_opener, token_matches
from telemetry_schema import validate as validate_telemetry, sanitize_local
import secrets
settings = Settings()
app=Flask(__name__)
app.config.update(
    SECRET_KEY=settings.secret, TRUSTED_HOSTS=settings.hosts,
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=settings.tls, SESSION_REFRESH_EACH_REQUEST=False,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=262144,
    MAX_FORM_MEMORY_SIZE=16384, MAX_FORM_PARTS=8,
)
limiter=Limiter(); sessions=Sessions(); outbound=secure_opener()

def dashboard_authenticated():
    return sessions.valid(session.get("sid"))

def csrf_token():
    if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(32)
    return session["csrf"]

app.jinja_env.globals["csrf_token"]=csrf_token

@app.before_request
def protect_dashboard():
    # Let Flask render invalid-host errors without touching untrusted host data.
    if request.routing_exception: return None
    if settings.tls and not request.is_secure:
        return jsonify({"error":"HTTPS required"}),400
    if settings.role=="agent" and request.endpoint!="health":
        return jsonify({"error":"agent has no dashboard"}),404
    if request.endpoint=="agent_report":
        if settings.role!="server": return jsonify({"error":"not a central server"}),404
        if not limiter.allow("reports-global",600,60) or not limiter.allow(("reports",request.remote_addr),30,60):
            return jsonify({"error":"rate limit exceeded"}),429
        return None
    if request.method=="POST":
        origin=request.headers.get("Origin")
        expected=request.host_url.rstrip("/")
        if origin and origin!=expected: return jsonify({"error":"invalid origin"}),403
        supplied=request.form.get("csrf_token","")
        known=session.get("csrf","")
        if not isinstance(known,str) or not known or not hmac.compare_digest(known.encode(),supplied.encode()):
            return jsonify({"error":"invalid CSRF token"}),403
    if request.endpoint in ("login","health","static"): return None
    if not dashboard_authenticated():
        if request.path.startswith("/api/"): return jsonify({"error":"authentication required"}),401
        return redirect(url_for("login"))
    if request.path.startswith("/api/") and not limiter.allow(("telemetry",session.get("sid")),60,60):
        return jsonify({"error":"rate limit exceeded"}),429

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    response.headers["Cache-Control"]="no-store"
    if settings.tls: response.headers["Strict-Transport-Security"]="max-age=31536000"
    return response

@app.get("/login")
@app.post("/login")
def login():
    if request.method=="GET": return render_template("login.html", error="")
    if not limiter.allow("login-global",30,300) or not limiter.allow(("login",request.remote_addr),5,300):
        return render_template("login.html",error="Too many attempts. Wait five minutes."),429
    username=request.form.get("username","")
    password=request.form.get("password","")
    expected_user=os.environ.get("NETSCOPE_AUTH_USERNAME","")
    password_hash=os.environ.get("NETSCOPE_AUTH_PASSWORD_HASH","")
    valid=False
    if len(username)<=64 and len(password)<=1024:
        try: valid=check_password_hash(password_hash,password) and hmac.compare_digest(username.encode(),expected_user.encode())
        except (ValueError,TypeError): pass
    if valid:
        sessions.revoke(session.get("sid"))
        sid=sessions.create()
        if sid is None: return jsonify({"error":"session capacity reached"}),503
        session.clear(); session["sid"]=sid; session["csrf"]=secrets.token_urlsafe(32); session.permanent=True
        return redirect(url_for("index"))
    return render_template("login.html",error="Incorrect username or password."),401

@app.post("/logout")
def logout():
    sessions.revoke(session.get("sid")); session.clear()
    return redirect(url_for("login"))

def load_agent_tokens():
    path=os.environ.get("NETSCOPE_AGENT_TOKENS_FILE","/etc/netscope/agents.json")
    try:
        with open(path,encoding="utf-8") as handle: value=json.loads(handle.read(262145))
        return value if isinstance(value,dict) and len(value)<=256 else {}
    except (OSError,ValueError): return {}

_status_cache={}; _status_cache_time=0; _status_lock=threading.Lock()
_previous={}; _previous_time=time.monotonic(); _alert_last={}; _alert_lock=threading.Lock()
_nodes={}; _nodes_lock=threading.Lock(); _agent_thread_started=False
_intel_cache={}; _intel_cache_time=0; _intel_lock=threading.Lock()

def notify_discord(key,message,cooldown=900):
    hook=os.environ.get("NETSCOPE_DISCORD_WEBHOOK","").strip()
    if not hook:return
    now=time.time()
    with _alert_lock:
        if now-_alert_last.get(key,0)<cooldown:return
        for stale in list(_alert_last):
            if now-_alert_last[stale]>3600: del _alert_last[stale]
        if len(_alert_last)>=512:return
        _alert_last[key]=now
    def send():
        try:
            body=json.dumps({"username":"NetScope","content":message[:1900]}).encode()
            req=urllib.request.Request(hook,data=body,headers={"Content-Type":"application/json"},method="POST")
            with outbound.open(req,timeout=4) as response: response.read(64)
        except Exception as exc:app.logger.warning("Discord webhook failed")
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
    commands=[["journalctl","-u","ssh.service","-u","sshd.service","--since","24 hours ago","-n","5000","--no-pager","-o","short-iso"]]
    for cmd in commands:
        try:
            import tempfile
            import resource
            # prlimit affects only the child process, never the threaded web worker.
            with tempfile.TemporaryFile() as output:
                completed=subprocess.run(["prlimit","--fsize=524288:524288","--"]+cmd,stdout=output,stderr=subprocess.DEVNULL,timeout=2,check=False)
                output.seek(0); raw=output.read(524288).decode("utf-8",errors="replace")
            if completed.returncode==0:sources.append("systemd journal")
            for line in raw.splitlines():
                if "Failed password" in line or "Invalid user" in line or "authentication failure" in line:
                    match=re.search(r"from ([0-9a-fA-F:.]+) port (\d+)",line)
                    user=re.search(r"(?:for invalid user|for) ([^ ]+)",line)
                    failed.append({"time":line[:25].strip(),"source_ip":match.group(1) if match else "Unknown","source_port":int(match.group(2)) if match else 0,"service":"SSH","target_port":22,"username":user.group(1) if user else "Unknown","event":"Invalid user" if "Invalid user" in line else "Failed authentication","message":line[:240]})
        except (ImportError,FileNotFoundError,subprocess.TimeoutExpired):pass
    if not sources:
        root=os.environ.get("NETSCOPE_HOST_ROOT","/").rstrip("/")
        for path in (root+"/var/log/auth.log",root+"/var/log/secure"):
            try:
                with open(path,"rb") as f:
                    f.seek(0,2); size=f.tell(); f.seek(max(0,size-512*1024))
                    raw=f.read(512*1024)
                lines=raw.decode("utf-8",errors="replace").splitlines()
                if size>512*1024: lines=lines[1:]
                lines=lines[-5000:]
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

def collect_local_status():
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
    return sanitize_local(data)

def get_local_status():
    global _status_cache, _status_cache_time
    with _status_lock:
        if _status_cache and time.monotonic()-_status_cache_time<3: return _status_cache
        _status_cache=collect_local_status(); _status_cache_time=time.monotonic()
        return _status_cache

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
            with outbound.open(req,timeout=5) as response:response.read(256)
        except Exception as exc:app.logger.warning("Could not report to central server")
        time.sleep(5)

def start_agent_sender():
    global _agent_thread_started
    if os.environ.get("NETSCOPE_ROLE","single").lower()!="agent" or _agent_thread_started:return
    _agent_thread_started=True
    threading.Thread(target=agent_sender,name="netscope-agent-reporter",daemon=True).start()

@app.get("/")
def index():return render_template("index.html")
@app.get("/api/status")
def status():
    try:
        return jsonify(get_local_status())
    except Exception as exc:
        app.logger.exception("Telemetry collection failed")
        return jsonify({"error":"Telemetry collection failed"}),503

@app.post("/api/agent/report")
def agent_report():
    try: body=request.get_json(silent=True)
    except (ValueError,RecursionError): return jsonify({"error":"invalid JSON report"}),400
    if not isinstance(body,dict): return jsonify({"error":"invalid report"}),400
    agent_id=body.get("agent_id","")
    if not isinstance(agent_id,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",agent_id):
        return jsonify({"error":"invalid agent ID"}),400
    registry=load_agent_tokens()
    if not token_matches(registry.get(agent_id),request.headers.get("X-NetScope-Token","")):
        return jsonify({"error":"unauthorized"}),401
    if not limiter.allow(("agent",agent_id),20,60): return jsonify({"error":"rate limit exceeded"}),429
    try: data=validate_telemetry(body.get("data"))
    except (ValueError,TypeError,OverflowError): return jsonify({"error":"invalid telemetry"}),400
    now=int(time.time())
    with _nodes_lock:
        for stale in list(_nodes):
            if stale not in registry or now-_nodes[stale]["last_seen"]>300: del _nodes[stale]
        _nodes[agent_id]={"name":agent_id,"agent_id":agent_id,"online":True,"last_seen":now,"data":data,"error":""}
    return jsonify({"accepted":True,"received_at":now})

@app.get("/api/network-intel")
def network_intel():
    try:
        return jsonify(get_network_intelligence())
    except Exception as exc:
        app.logger.exception("Network intelligence collection failed")
        return jsonify({"error":"Network intelligence unavailable"}),503

@app.get("/api/cluster")
def cluster():
    result=[]
    try: local=get_local_status()
    except Exception:
        app.logger.exception("Telemetry collection failed")
        return jsonify({"error":"Telemetry collection failed"}),503
    result.append({"name":local["hostname"]+" (central)","url":"local","online":True,"last_seen":int(time.time()),"data":local,"kind":"central"})
    now=int(time.time()); registry=load_agent_tokens()
    with _nodes_lock:
        for key in list(_nodes):
            if key not in registry or now-_nodes[key]["last_seen"]>300: del _nodes[key]
        reports=list(_nodes.values())
    for node in reports:
        online=now-node["last_seen"]<=25
        result.append({**node,"online":online,"kind":"agent","error":"" if online else "No recent heartbeat"})
        if not online:notify_discord("agent-offline:"+node["agent_id"],"NetScope agent offline: "+node['agent_id'])
    return jsonify({"mode":"cluster","nodes":result,"online":sum(1 for n in result if n["online"]),"total":len(result)})

@app.get("/health")
def health():return jsonify({"status":"ok","service":"netscope"})

if __name__=="__main__":
    if settings.role!="agent": raise SystemExit("Start the dashboard with Gunicorn")
    agent_sender()

