#!/usr/bin/env python3
"""Read-only NetScope Pro host and network telemetry."""
from flask import Flask, jsonify, render_template
import os, platform, psutil, socket, time
app = Flask(__name__)
_previous = {}
_previous_time = time.monotonic()

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/status")
def status():
    global _previous, _previous_time
    now = time.monotonic()
    elapsed = max(now - _previous_time, 0.001)
    counters = psutil.net_io_counters(pernic=True)
    stats, addresses = psutil.net_if_stats(), psutil.net_if_addrs()
    interfaces, next_previous = [], {}
    for name, c in counters.items():
        old = _previous.get(name)
        rx = max(0, (c.bytes_recv - old[0]) / elapsed) if old else 0
        tx = max(0, (c.bytes_sent - old[1]) / elapsed) if old else 0
        next_previous[name] = (c.bytes_recv, c.bytes_sent)
        st = stats.get(name)
        ipv4 = next((a.address for a in addresses.get(name, []) if a.family == socket.AF_INET), "")
        interfaces.append({"name":name,"ipv4":ipv4,"is_up":bool(st and st.isup),"speed_mbps":st.speed if st else 0,"mtu":st.mtu if st else 0,"rx_rate":rx,"tx_rate":tx,"rx_total":c.bytes_recv,"tx_total":c.bytes_sent,"packets_recv":c.packets_recv,"packets_sent":c.packets_sent,"errors_in":c.errin,"errors_out":c.errout,"drops_in":c.dropin,"drops_out":c.dropout})
    _previous, _previous_time = next_previous, now
    mem, swap, disk = psutil.virtual_memory(), psutil.swap_memory(), psutil.disk_usage("/")
    freq = psutil.cpu_freq()
    load = os.getloadavg() if hasattr(os, "getloadavg") else [0,0,0]
    processes = []
    for p in psutil.process_iter(["pid","name","username","memory_percent"]):
        try:
            x=p.info
            processes.append({"pid":x.get("pid"),"name":x.get("name") or "unknown","user":x.get("username") or "","memory_percent":round(x.get("memory_percent") or 0,2)})
        except (psutil.NoSuchProcess,psutil.AccessDenied): pass
    processes.sort(key=lambda x:x["memory_percent"],reverse=True)
    return jsonify({"timestamp":int(time.time()),"hostname":socket.gethostname(),"fqdn":socket.getfqdn(),"os":platform.platform(),"kernel":platform.release(),"cpu_percent":psutil.cpu_percent(interval=None),"cpu_count":psutil.cpu_count(logical=True) or 0,"cpu_physical":psutil.cpu_count(logical=False) or 0,"cpu_frequency_mhz":freq.current if freq else 0,"load_1":load[0],"load_5":load[1],"load_15":load[2],"memory_percent":mem.percent,"memory_used":mem.used,"memory_total":mem.total,"memory_available":mem.available,"swap_percent":swap.percent,"swap_used":swap.used,"swap_total":swap.total,"disk_percent":disk.percent,"disk_used":disk.used,"disk_total":disk.total,"disk_free":disk.free,"uptime":int(time.time()-psutil.boot_time()),"interfaces":interfaces,"processes":processes[:8]})

@app.get("/health")
def health():
    return jsonify({"status":"ok","service":"netscope-pro"})

if __name__ == "__main__":
    app.run(host=os.environ.get("NETSCOPE_HOST","0.0.0.0"),port=int(os.environ.get("NETSCOPE_PORT","8080")))
