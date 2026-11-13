#!/usr/bin/env python3
"""Small, read-only NetScope Pro VM dashboard."""
from flask import Flask, jsonify, render_template_string
import psutil
import socket
import time
import os

app = Flask(__name__)
STARTED = time.time()

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NetScope Pro</title>
<style>
:root{color-scheme:dark;--bg:#080d18;--panel:#111a2b;--line:#24334c;--muted:#91a2bd;--text:#edf3ff;--accent:#ff8a35}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% 0%,#17243a 0,#080d18 45%);font:15px system-ui;color:var(--text)}
main{max-width:1100px;margin:40px auto;padding:0 20px}.top{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:27px;letter-spacing:.3px}.sub,.muted{color:var(--muted)}.pill{border:1px solid #31543f;color:#8de0a9;border-radius:20px;padding:7px 12px;font-size:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-top:26px}
.card{background:linear-gradient(145deg,#151f32,#0f1727);border:1px solid var(--line);border-radius:14px;padding:20px;min-height:125px}
.label{color:var(--muted);font-size:13px}.value{font-size:27px;font-weight:650;margin-top:12px}.unit{font-size:13px;color:var(--muted);font-weight:400}
section{margin-top:22px}.section-title{font-size:16px;margin-bottom:12px}.interfaces{display:grid;gap:10px}
.iface{display:flex;justify-content:space-between;gap:12px;padding:14px 16px;background:#0e1727;border:1px solid var(--line);border-radius:10px;flex-wrap:wrap}
footer{margin:28px 0;color:var(--muted);font-size:12px}
</style></head><body><main>
<div class="top"><div><h1>NetScope <span style="color:var(--accent)">Pro</span></h1><div class="sub">VM system and network overview</div></div><div class="pill">● Agent online</div></div>
<div class="grid">
<div class="card"><div class="label">CPU usage</div><div class="value" id="cpu">—</div></div>
<div class="card"><div class="label">Memory usage</div><div class="value" id="mem">—</div></div>
<div class="card"><div class="label">System uptime</div><div class="value" id="uptime">—</div></div>
<div class="card"><div class="label">Hostname</div><div class="value" id="host">—</div></div>
</div>
<section><div class="section-title">Network interfaces</div><div class="interfaces" id="interfaces"><div class="muted">Loading interface counters…</div></div></section>
<footer>NetScope Pro · Read-only local telemetry · Refreshes every 3 seconds</footer>
</main><script>
function bytes(n){if(n<1024)return n+' B/s';let u=['KB/s','MB/s','GB/s'],i=-1;do{n/=1024;i++}while(n>=1024&&i<u.length-1);return n.toFixed(1)+' '+u[i]}
function duration(s){let d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return (d?d+'d ':'')+h+'h '+m+'m'}
async function refresh(){try{let r=await fetch('/api/status',{cache:'no-store'}),d=await r.json();
document.getElementById('cpu').textContent=d.cpu_percent.toFixed(1)+'%';
document.getElementById('mem').textContent=d.memory_percent.toFixed(1)+'%';
document.getElementById('uptime').textContent=duration(d.uptime);
document.getElementById('host').textContent=d.hostname;
document.getElementById('interfaces').innerHTML=d.interfaces.map(n=>'<div class="iface"><strong>'+n.name+'</strong><span>RX '+bytes(n.rx_rate)+'</span><span>TX '+bytes(n.tx_rate)+'</span><span class="muted">'+(n.is_up?'UP':'DOWN')+'</span></div>').join('')||'<div class="muted">No interfaces found</div>';
}catch(e){document.getElementById('interfaces').textContent='Unable to reach the NetScope agent';}}
refresh();setInterval(refresh,3000);
</script></body></html>"""

_previous = {}
_previous_time = time.monotonic()

@app.get("/")
def index():
    return render_template_string(PAGE)

@app.get("/api/status")
def status():
    global _previous, _previous_time
    now = time.monotonic()
    counters = psutil.net_io_counters(pernic=True)
    elapsed = max(now - _previous_time, 0.001)
    interfaces = []
    for name, c in counters.items():
        old = _previous.get(name)
        rx = (c.bytes_recv - old[0]) / elapsed if old else 0
        tx = (c.bytes_sent - old[1]) / elapsed if old else 0
        interfaces.append({
            "name": name,
            "rx_rate": max(rx, 0),
            "tx_rate": max(tx, 0),
            "is_up": bool(psutil.net_if_stats().get(name) and psutil.net_if_stats()[name].isup)
        })
    _previous = {name: (c.bytes_recv, c.bytes_sent) for name, c in counters.items()}
    _previous_time = now
    mem = psutil.virtual_memory()
    return jsonify({
        "hostname": socket.gethostname(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": mem.percent,
        "uptime": int(time.time() - psutil.boot_time()),
        "interfaces": interfaces
    })

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "netscope-pro"})

if __name__ == "__main__":
    app.run(host=os.environ.get("NETSCOPE_HOST", "0.0.0.0"),
            port=int(os.environ.get("NETSCOPE_PORT", "8080")))
