#!/usr/bin/env python3
"""NetScope: read-only Linux telemetry with central push-agent clustering."""
from flask import Flask, jsonify, render_template, request
import os, platform, psutil, socket, time, json, threading, urllib.request, hmac
app=Flask(__name__)
_previous={}; _previous_time=time.monotonic(); _alert_last={}; _alert_lock=threading.Lock()
_nodes={}; _nodes_lock=threading.Lock(); _agent_thread_started=False

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
    data={"timestamp":int(time.time()),"hostname":socket.gethostname(),"fqdn":socket.getfqdn(),"primary_ip":next((i["ipv4"] for i in interfaces if i["ipv4"] and i["name"]!="lo"),""),"os":platform.platform(),"kernel":platform.release(),"cpu_percent":psutil.cpu_percent(interval=None),"cpu_count":psutil.cpu_count(logical=True) or 0,"cpu_physical":psutil.cpu_count(logical=False) or 0,"cpu_frequency_mhz":freq.current if freq else 0,"load_1":load[0],"load_5":load[1],"load_15":load[2],"memory_percent":mem.percent,"memory_used":mem.used,"memory_total":mem.total,"memory_available":mem.available,"swap_percent":swap.percent,"swap_used":swap.used,"swap_total":swap.total,"disk_percent":disk.percent,"disk_used":disk.used,"disk_total":disk.total,"disk_free":disk.free,"uptime":int(time.time()-psutil.boot_time()),"interfaces":interfaces,"processes":sorted(processes,key=lambda x:x["memory_percent"],reverse=True)[:8]}
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
    if not server or not token:
        app.logger.error("Agent mode needs NETSCOPE_SERVER_URL and NETSCOPE_AGENT_TOKEN."); return
    while True:
        try:
            data=get_local_status()
            payload=json.dumps({"name":socket.gethostname(),"agent_id":socket.gethostname(),"data":data}).encode()
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
def index():return render_template("index.html")
@app.get("/api/status")
def status():return jsonify(get_local_status())

@app.post("/api/agent/report")
def agent_report():
    expected=os.environ.get("NETSCOPE_AGENT_TOKEN","").strip()
    supplied=request.headers.get("X-NetScope-Token","")
    if not expected or not hmac.compare_digest(expected,supplied):return jsonify({"error":"unauthorized"}),401
    body=request.get_json(silent=True) or {}; name=str(body.get("name","")).strip()[:80]; data=body.get("data")
    if not name or not isinstance(data,dict) or not data.get("hostname"):return jsonify({"error":"invalid report"}),400
    now=int(time.time())
    with _nodes_lock:_nodes[name]={"name":name,"agent_id":str(body.get("agent_id",name))[:100],"online":True,"last_seen":now,"data":data,"error":""}
    return jsonify({"accepted":True,"received_at":now})

@app.get("/api/cluster")
def cluster():
    role=os.environ.get("NETSCOPE_ROLE","single").lower(); result=[]
    if role!="agent":
        local=get_local_status()
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
