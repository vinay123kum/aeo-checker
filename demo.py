"""Render a sample report with no API keys. All brands and results are fictional."""
import json, random
from pathlib import Path
import aeo_check, report

d = json.loads(Path("example_manual.json").read_text(encoding="utf-8"))
P = ["google", "perplexity", "bing", "claude", "gemini"]
random.seed(11)


def company(brand, domain, rate):
    res = {q: {p: {"status": "cited" if random.random() < rate else "not_cited"} for p in P} for q in d["keywords"]}
    return {"brand": brand, "domain": domain, "results": res, "score": aeo_check.score(res, d["keywords"])["score"]}


prospect = company(d["brand"], d["domain"], .2)
rates = [.72, .58, .46, .34, .25]
comps = [company(c["name"], c["domain"], r) for c, r in zip(d["competitors"], rates)]
recs = [{"title": t, "bullets": b, "priority": pr} for t, b, pr in [
    ("Publish listicles for buyer queries", ["Target each query you lose", "Include a comparison table", "Refresh quarterly"], "Critical"),
    ("Earn third-party citations", ["Pitch category roundups", "Update review profiles", "Answer community threads"], "Critical"),
    ("Add answer-first page sections", ["Lead with a direct answer", "Use question headings", "Keep claims sourced"], "High"),
    ("Mark up key pages", ["Add FAQ schema", "Add product schema", "Validate monthly"], "High"),
    ("Build comparison pages", ["Cover the top rivals", "State real tradeoffs", "Link from the main nav"], "Medium"),
    ("Track citations monthly", ["Rerun this report", "Log gained and lost queries", "Share with content owners"], "Medium")]]
Path("sample_report.html").write_text(report.render(prospect, comps, d["keywords"], None, P, recs), encoding="utf-8")
print("Wrote sample_report.html")
