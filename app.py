#!/usr/bin/env python3
"""
AEO Checker — web app. One URL field in, AI-visibility report out.

  python app.py   ->  http://localhost:5050

Deploy: railway.toml is included; `Procfile` runs gunicorn app:app.
"""

import threading
import uuid

from flask import Flask, request, jsonify, Response

import aeo_check
import discover as disc
import report as rep

app = Flask(__name__)
JOBS = {}  # id -> {"status","log","html","brand","score"}

FORM = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AEO Checker</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f0c29;color:#fff;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{max-width:560px;width:90%;text-align:center;padding:40px}
h1{font-size:34px;font-weight:900;margin:0 0 10px}
.sub{color:rgba(255,255,255,.6);margin-bottom:32px}
.row{display:flex;gap:10px}
input{flex:1;padding:15px 18px;border-radius:10px;border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.07);color:#fff;font-size:16px}
button{padding:15px 26px;border-radius:10px;border:0;background:#f97316;color:#fff;font-weight:800;font-size:16px;cursor:pointer}
button:disabled{opacity:.5}
#log{margin-top:26px;text-align:left;font-family:ui-monospace,monospace;font-size:12px;color:#a78bfa;max-height:260px;overflow:auto;white-space:pre-wrap}
a.report{display:inline-block;margin-top:22px;background:#fff;color:#ea580c;padding:13px 28px;border-radius:9px;text-decoration:none;font-weight:800}
.platforms{margin-top:18px;font-size:12px;color:rgba(255,255,255,.45)}
</style></head><body><div class="card">
<h1>AI Visibility Checker</h1>
<div class="sub">Enter a website. See how often AI engines cite it for buyer queries.</div>
<div class="row">
  <input id="url" placeholder="example.com" autofocus>
  <button id="go" onclick="go()">Check</button>
</div>
<div class="platforms">Active platforms: __PLATFORMS__</div>
<div id="log"></div>
<div id="out"></div>
</div><script>
async function go(){
  const url=document.getElementById('url').value.trim();
  if(!url)return;
  document.getElementById('go').disabled=true;
  document.getElementById('out').innerHTML='';
  const log=document.getElementById('log');log.textContent='Discovering brand, keywords & competitors…\\n';
  const r=await fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})});
  const {id}=await r.json();
  const t=setInterval(async()=>{
    const s=await (await fetch('/status/'+id)).json();
    log.textContent=s.log.join('\\n');log.scrollTop=log.scrollHeight;
    if(s.status==='done'){clearInterval(t);document.getElementById('go').disabled=false;
      document.getElementById('out').innerHTML='<a class="report" href="/report/'+id+'" target="_blank">Open report — '+s.brand+' scored '+s.score+'/10 →</a>';}
    if(s.status==='error'){clearInterval(t);document.getElementById('go').disabled=false;log.textContent+='\\nERROR: '+s.error;}
  },1200);
}
document.getElementById('url').addEventListener('keydown',e=>{if(e.key==='Enter')go()});
</script></body></html>"""


def worker(job_id, url):
    job = JOBS[job_id]
    try:
        d = disc.discover(url)
        platforms = aeo_check.active_platforms()
        queries = d["keywords"]
        job["log"].append(f"Brand: {d['brand']} ({d['domain']})")
        job["log"].append(f"Platforms: {', '.join(platforms)}")
        job["log"].append(f"Keywords: {len(queries)} | Competitors: {len(d['competitors'])}")

        def prog(brand, q, p, status):
            mark = "✓" if status == "cited" else "·" if status == "not_cited" else "○"
            job["log"].append(f"  {mark} [{p}] {brand[:18]} — {q[:34]}")

        prospect = {"brand": d["brand"], "domain": d["domain"]}
        prospect["results"] = aeo_check.run_company(d["brand"], d["domain"], queries, prog)
        prospect["score"] = aeo_check.score(prospect["results"], queries)["score"]

        competitors = []
        for c in d["competitors"]:
            res = aeo_check.run_company(c["name"], c["domain"], queries, prog)
            competitors.append({"brand": c["name"], "domain": c["domain"], "results": res,
                                "score": aeo_check.score(res, queries)["score"]})

        job["html"] = rep.render(prospect, competitors, queries, None, platforms)
        job["brand"] = prospect["brand"]
        job["score"] = prospect["score"]
        job["status"] = "done"
        job["log"].append(f"\nDone — {prospect['brand']} scored {prospect['score']}/10")
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.route("/")
def index():
    plats = ", ".join(aeo_check.active_platforms()) or "none — add keys to .env"
    return Response(FORM.replace("__PLATFORMS__", plats), mimetype="text/html")


@app.route("/start", methods=["POST"])
def start():
    url = (request.json or {}).get("url", "").strip()
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"status": "running", "log": [], "html": "", "brand": "", "score": 0}
    threading.Thread(target=worker, args=(job_id, url), daemon=True).start()
    return jsonify({"id": job_id})


@app.route("/status/<job_id>")
def status(job_id):
    j = JOBS.get(job_id, {})
    return jsonify({k: j.get(k) for k in ("status", "log", "brand", "score", "error")})


@app.route("/report/<job_id>")
def report_view(job_id):
    return Response(JOBS.get(job_id, {}).get("html", "Not found"), mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
