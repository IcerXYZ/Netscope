#!/usr/bin/env python3
"""NetScope Pro read-only host telemetry, optional cluster view and Discord alerts."""
from flask import Flask, jsonify, render_template
import os, platform, psutil, socket, time, json, threading, urllib.request
app=Flask(__name__)
_previous={}
_previous_time=time.monotonic()
_alert_last={}
_alert_lock=threading.Lock()

def notify_discord(key,message,cooldown=900):
    hook=os.environ.get("NETSCOPE_DISCORD_WEBHOOK","").strip()
    if not hook:return
    now=time.time()
    with _alert_lock:
        if now-_alert_last.get(key,0)<cooldown:return
        _alert_last[key]=now
    def send():
        try:
            body=json.dumps({"username":"NetScope Pro","content":message[:1900]}).encode()
            req=urllib.request.Request(hook,data=body,headers={"Content-Type":"application/json"},method="POST")
            urllib.request.urlopen(req,timeout=4).read(64)
        except Exception as exc: app.logger.warning("Discord webhook failed: %s",exc)
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
    mem,swap,disk=psutil.virtual_memory(),psutil.swap_memory(),psutil.disk_usage("/")
    freq=psutil.cpu_freq(); load=os.getloadavg() if hasattr(os,"getloadavg") else [0,0,0]
    processes=[]
    for p in psutil.process_iter(["pid","name","username","memory_percent"]):
        try:
            x=p.info; processes.append({"pid":x.get("pid"),"name":x.get("name") or "unknown","user":x.get("username") or "","memory_percent":round(x.get("memory_percent") or 0,2)})
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    data={"timestamp":int(time.time()),"hostname":socket.gethostname(),"fqdn":socket.getfqdn(),"primary_ip":next((i["ipv4"] for i in interfaces if i["ipv4"] and i["name"]!="lo"),""),"os":platform.platform(),"kernel":platform.release(),"cpu_percent":psutil.cpu_percent(interval=None),"cpu_count":psutil.cpu_count(logical=True) or 0,"cpu_physical":psutil.cpu_count(logical=False) or 0,"cpu_frequency_mhz":freq.current if freq else 0,"load_1":load[0],"load_5":load[1],"load_15":load[2],"memory_percent":mem.percent,"memory_used":mem.used,"memory_total":mem.total,"memory_available":mem.available,"swap_percent":swap.percent,"swap_used":swap.used,"swap_total":swap.total,"disk_percent":disk.percent,"disk_used":disk.used,"disk_total":disk.total,"disk_free":disk.free,"uptime":int(time.time()-psutil.boot_time()),"interfaces":interfaces,"processes":sorted(processes,key=lambda x:x["memory_percent"],reverse=True)[:8]}
    for metric,value in (("CPU",data["cpu_percent"]),("RAM",data["memory_percent"]),("Disk",data["disk_percent"])):
        if value>=90:notify_discord(socket.gethostname()+":"+metric,f"⚠️ **NetScope Pro alert — {socket.gethostname()}**\\n{metric} usage is {value:.1f}% (90% threshold).")
    return data

def nodes_config():
    try:
        value=json.loads(os.environ.get("NETSCOPE_NODES","[]"))
        return [{"name":str(n["name"]),"url":str(n["url"]).rstrip("/")} for n in value if n.get("name") and n.get("url")]
    except (ValueError,TypeError,KeyError):
        app.logger.warning("Invalid NETSCOPE_NODES JSON; expected [{\"name\":\"node2\",\"url\":\"http://10.0.0.2:8080\"}]")
        return []

@app.get("/")
def index():return render_template("index.html")
@app.get("/api/status")
def status():return jsonify(get_local_status())
@app.get("/api/cluster")
def cluster():
    local=get_local_status(); result=[{"name":local["hostname"],"url":"local","online":True,"data":local}]
    for node in nodes_config():
        try:
            req=urllib.request.Request(node["url"]+"/api/status",headers={"User-Agent":"NetScope-Pro"})
            with urllib.request.urlopen(req,timeout=3) as response:data=json.loads(response.read(2000000))
            result.append({"name":node["name"],"url":node["url"],"online":True,"data":data})
        except Exception as exc:
            result.append({"name":node["name"],"url":node["url"],"online":False,"error":str(exc)[:140],"data":None})
            notify_discord("node:"+node["name"],f"🔴 **NetScope Pro — node offline**\\n{node['name']} ({node['url']}) is not responding.")
    return jsonify({"mode":"cluster","nodes":result,"online":sum(1 for n in result if n["online"]),"total":len(result)})
@app.get("/health")
def health():return jsonify({"status":"ok","service":"netscope-pro"})
if __name__=="__main__":app.run(host=os.environ.get("NETSCOPE_HOST","0.0.0.0"),port=int(os.environ.get("NETSCOPE_PORT","8080")))
