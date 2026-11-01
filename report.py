#!/usr/bin/env python3
"""
Render the AEO visibility report as a single self-contained HTML file.
Follows the SEO-expert-approved structure:
  Cover score -> Score + 5 BOF keywords -> Competitor dot-table -> Recommendations -> CTA
"""

import html
import os
from pathlib import Path

# Load .env so this module works standalone too
_env = Path(__file__).parent / ".env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        if "=" in _l and not _l.lstrip().startswith("#"):
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

try:
    import anthropic
except ImportError:
    anthropic = None

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SERVICE_URL = os.environ.get("REPORT_CTA_URL", "#")
AGENCY_NAME = os.environ.get("REPORT_AGENCY_NAME", "AEO Checker")


def _pill_color(s):
    return "#16a34a" if s >= 7 else "#d97706" if s >= 4 else "#dc2626"


def query_dot(results, query, platforms):
    """Aggregate a query's per-platform citations into one dot color."""
    ran = [p for p in platforms if results.get(query, {}).get(p, {}).get("status") in ("cited", "not_cited")]
    cited = [p for p in ran if results.get(query, {}).get(p, {}).get("status") == "cited"]
    if not ran:
        return "#cbd5e1", "n/a"
    frac = len(cited) / len(ran)
    if frac >= 0.5:
        return "#16a34a", f"{len(cited)}/{len(ran)}"
    if frac > 0:
        return "#d97706", f"{len(cited)}/{len(ran)}"
    return "#dc2626", f"0/{len(ran)}"


def short_label(q, n=22):
    q = q.strip()
    return (q[:n] + "…") if len(q) > n else q


def recommendations(brand, prospect_score, best_comp, gap):
    """Six prioritized recommendation cards. Claude → Gemini → template."""
    import json
    import re
    import requests
    prompt = (f"Write exactly 6 AEO/GEO recommendations for {brand}, which scored "
              f"{prospect_score}/10 on AI visibility ({gap} points behind {best_comp}). "
              'Return ONLY valid JSON: a list of 6 objects {"title": "...", '
              '"bullets": ["b1","b2","b3"], "priority": "Critical|High|Medium"}. '
              "Be specific to closing an AI citation gap (earning high-authority citations, "
              "listicle/comparison content, schema, topical authority). No prose outside JSON.")

    def _extract(t):
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", t)
        return json.loads(m.group(1) if m else t)[:6]

    if ANTHROPIC_KEY and anthropic:
        try:
            client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
            resp = client.messages.create(
                model="claude-opus-4-8", max_tokens=1400,
                messages=[{"role": "user", "content": prompt}])
            return _extract(resp.content[0].text.strip())
        except Exception:
            pass

    gkey = os.environ.get("GEMINI_API_KEY", "")
    if gkey:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={gkey}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"responseMimeType": "application/json"}},
                timeout=60)
            d = r.json()
            if "error" not in d:
                return _extract(d["candidates"][0]["content"]["parts"][0]["text"])
        except Exception:
            pass
    # Template fallback
    return [
        {"title": "Earn high-authority citations on your money queries",
         "bullets": ["Place comparison content on sites AI engines already trust",
                     "Target the exact 5 BOF queries in this report",
                     "Prioritize listicles where competitors are currently cited"],
         "priority": "Critical"},
        {"title": "Publish the listicle for every query you're losing",
         "bullets": ["AI Overviews pull from 'best X' / 'top X' pages",
                     "One ranking listicle per query = the fastest citation win",
                     "Include your brand as the lead recommendation"],
         "priority": "Critical"},
        {"title": "Structure content for AI answer extraction",
         "bullets": ["Add FAQ + HowTo schema to key pages",
                     "Lead each section with a direct, quotable answer",
                     "Use clear headings that mirror buyer questions"],
         "priority": "High"},
        {"title": "Build topical authority around your category",
         "bullets": ["Cluster content around the core buyer problem",
                     "Internally link supporting pages to your money pages",
                     "Earn mentions on category roundup pages"],
         "priority": "High"},
        {"title": "Get listed in third-party comparison sources",
         "bullets": ["G2, Capterra, and editorial roundups feed AI answers",
                     "Ensure your profile is complete and review-rich",
                     "Pitch inclusion in 'alternatives to' articles"],
         "priority": "Medium"},
        {"title": "Monitor and re-test monthly",
         "bullets": ["Re-run this AEO check every 30 days",
                     "Track score movement per query and per platform",
                     "Double down where citations start landing"],
         "priority": "Medium"},
    ]


def render(prospect, competitors, queries, scores, platforms, recs=None):
    """
    prospect = {"brand","domain","results","score"}
    competitors = [{"brand","domain","results","score"}, ...]
    scores already computed; platforms = active platform keys.
    """
    p_score = prospect["score"]
    comp_sorted = sorted(competitors, key=lambda c: c["score"], reverse=True)
    best = comp_sorted[0] if comp_sorted else {"brand": "—", "score": 0.0}
    gap = round(best["score"] - p_score, 1)

    if recs is None:
        recs = recommendations(prospect["brand"], p_score, best["brand"], gap)

    rows = [prospect] + comp_sorted
    plat_names = {"google": "Google AIO", "perplexity": "Perplexity", "bing": "Bing",
                  "claude": "Claude", "gemini": "Gemini"}
    active_label = ", ".join(plat_names.get(p, p) for p in platforms)

    # Keyword list
    kw_html = "".join(
        f'<li><span class="kw-num">{i+1}</span><span class="kw-text">{html.escape(q)}</span>'
        f'<span class="kw-tag">BOF</span></li>'
        for i, q in enumerate(queries)
    )

    # Table header
    th = "".join(f'<th title="{html.escape(q)}">{html.escape(short_label(q))}</th>' for q in queries)

    # Table rows
    tr_html = ""
    for r in rows:
        is_p = r is prospect
        cells = ""
        for q in queries:
            color, lab = query_dot(r["results"], q, platforms)
            cells += f'<td><span class="dot" style="background:{color}" title="{lab} platforms cited"></span></td>'
        pill = _pill_color(r["score"])
        name = html.escape(r["brand"]) + (' <span class="you">← YOU</span>' if is_p else "")
        tr_html += (f'<tr class="{"prospect-row" if is_p else ""}">'
                    f'<td class="cname">{name}</td>{cells}'
                    f'<td><span class="pill" style="background:{pill}">{r["score"]}</span></td></tr>')

    # Recommendation cards
    pri_color = {"Critical": "#dc2626", "High": "#d97706", "Medium": "#2563eb"}
    rec_html = ""
    for i, rec in enumerate(recs):
        bullets = "".join(f"<li>{html.escape(b)}</li>" for b in rec.get("bullets", []))
        pr = rec.get("priority", "High")
        rec_html += (f'<div class="rec-card"><div class="rec-num">{i+1}</div>'
                     f'<h4>{html.escape(rec.get("title",""))}</h4><ul>{bullets}</ul>'
                     f'<span class="rec-pri" style="background:{pri_color.get(pr,"#2563eb")}">{html.escape(pr)}</span></div>')

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Visibility Report — {html.escape(prospect['brand'])}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f1f5f9;color:#0f172a;line-height:1.5}}
.wrap{{max-width:980px;margin:0 auto;background:#fff}}
.cover{{background:linear-gradient(135deg,#0f0c29,#302b63 55%,#24243e);color:#fff;padding:64px 56px}}
.cover-badge{{font-size:12px;letter-spacing:3px;text-transform:uppercase;color:#a78bfa;font-weight:600;margin-bottom:18px}}
.cover h1{{font-size:40px;font-weight:900;line-height:1.1}}
.cover-sub{{font-size:16px;color:rgba(255,255,255,.65);margin-top:18px;max-width:620px}}
.hero{{display:flex;gap:18px;margin-top:36px}}
.hero-card{{flex:1;border-radius:14px;padding:26px 20px;text-align:center}}
.hero-you{{background:rgba(255,107,107,.12);border:1px solid rgba(255,107,107,.4)}}
.hero-comp{{background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.35)}}
.hero-gap{{background:rgba(251,146,60,.12);border:1px solid rgba(251,146,60,.35)}}
.hero-num{{font-size:54px;font-weight:900;line-height:1}}
.hero-num.you{{color:#ff6b6b;font-size:54px;font-weight:900;letter-spacing:0}} .hero-num.comp{{color:#4ade80}} .hero-num.gap{{color:#fb923c}}
.hero-lab{{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:rgba(255,255,255,.6);margin-top:10px}}
.section{{padding:48px 56px;border-bottom:1px solid #eef2f7}}
.section h2{{font-size:24px;font-weight:800;color:#1e1b4b;margin-bottom:6px}}
.section .desc{{font-size:14px;color:#64748b;margin-bottom:28px}}
.kw-list{{list-style:none}}
.kw-list li{{display:flex;align-items:center;gap:14px;padding:13px 16px;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:9px;background:#fafbff}}
.kw-num{{width:26px;height:26px;border-radius:50%;background:#4f46e5;color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0}}
.kw-text{{flex:1;font-size:15px;color:#1e293b}}
.kw-tag{{font-size:10px;font-weight:700;color:#7c3aed;background:#ede9fe;padding:3px 8px;border-radius:5px;letter-spacing:.5px}}
table{{width:100%;border-collapse:collapse;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
th{{background:#1e1b4b;color:#fff;padding:13px 12px;font-size:11px;text-transform:uppercase;letter-spacing:.4px;text-align:center}}
th:first-child{{text-align:left}}
td{{padding:12px;border-bottom:1px solid #f1f5f9;font-size:14px;text-align:center}}
td.cname{{text-align:left;font-weight:600;color:#334155}}
tr.prospect-row td{{background:#eef2ff!important;border-left:3px solid #ff6b6b}}
.you{{font-size:10px;color:#ff6b6b;font-weight:700;letter-spacing:.5px}}
.dot{{display:inline-block;width:15px;height:15px;border-radius:50%}}
.pill{{display:inline-block;padding:4px 13px;border-radius:20px;color:#fff;font-weight:800;font-size:14px}}
.legend{{margin-top:16px;font-size:12px;color:#64748b;display:flex;gap:18px;flex-wrap:wrap}}
.legend span{{display:flex;align-items:center;gap:6px}}
.recs{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
.rec-card{{border:1px solid #e2e8f0;border-radius:12px;padding:24px;position:relative;background:#fff}}
.rec-num{{width:30px;height:30px;border-radius:7px;background:#f97316;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;margin-bottom:12px}}
.rec-card h4{{font-size:16px;color:#1e1b4b;margin-bottom:12px}}
.rec-card ul{{list-style:none;margin-bottom:16px}}
.rec-card li{{font-size:13.5px;color:#475569;padding:5px 0 5px 18px;position:relative}}
.rec-card li::before{{content:"→";position:absolute;left:0;color:#f97316;font-weight:700}}
.rec-pri{{display:inline-block;color:#fff;font-size:10px;font-weight:700;padding:4px 11px;border-radius:5px;letter-spacing:.5px}}
.cta{{background:linear-gradient(135deg,#f97316,#ea580c);color:#fff;padding:52px 56px;text-align:center}}
.cta h2{{font-size:26px;font-weight:800;margin-bottom:12px}}
.cta p{{color:rgba(255,255,255,.9);margin-bottom:24px;font-size:15px}}
.cta a{{display:inline-block;background:#fff;color:#ea580c;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:800}}
.foot{{padding:22px 56px;font-size:12px;color:#94a3b8;background:#0f0c29}}
@media(max-width:680px){{.hero,.recs{{flex-direction:column;grid-template-columns:1fr}}.section,.cover,.cta{{padding-left:24px;padding-right:24px}}}}
</style></head><body><div class="wrap">

<div class="cover">
  <div class="cover-badge">AI Visibility Report</div>
  <h1>{html.escape(prospect['brand'])}</h1>
  <div class="cover-sub">Tested across {len(queries)} bottom-of-funnel buyer queries on {active_label}. Score = how often you're cited in AI answers, out of every available slot.</div>
  <div class="hero">
    <div class="hero-card hero-you"><div class="hero-num you">{p_score}</div><div class="hero-lab">{html.escape(prospect['brand'])} score /10</div></div>
    <div class="hero-card hero-comp"><div class="hero-num comp">{best['score']}</div><div class="hero-lab">Top competitor ({html.escape(best['brand'])})</div></div>
    <div class="hero-card hero-gap"><div class="hero-num gap">{gap}</div><div class="hero-lab">Visibility gap</div></div>
  </div>
</div>

<div class="section">
  <h2>Visibility Score &amp; Target Keywords</h2>
  <div class="desc">The {len(queries)} bottom-of-funnel queries your buyers use when they're ready to choose a vendor.</div>
  <ul class="kw-list">{kw_html}</ul>
</div>

<div class="section">
  <h2>Competitor Comparison</h2>
  <div class="desc">Each dot = how many AI platforms cited that brand for the query. Green ≥ half, amber = some, red = none.</div>
  <table><thead><tr><th>Company</th>{th}<th>Score</th></tr></thead><tbody>{tr_html}</tbody></table>
  <div class="legend">
    <span><span class="dot" style="background:#16a34a"></span> Cited (majority)</span>
    <span><span class="dot" style="background:#d97706"></span> Cited (some)</span>
    <span><span class="dot" style="background:#dc2626"></span> Not cited</span>
    <span><span class="dot" style="background:#cbd5e1"></span> No data</span>
  </div>
</div>

<div class="section">
  <h2>Recommendations</h2>
  <div class="desc">How to close the AI citation gap, prioritized by impact.</div>
  <div class="recs">{rec_html}</div>
</div>

<div class="cta">
  <h2>Close your AI visibility gap</h2>
  <p>A focused AEO/GEO program makes you the source AI engines cite.</p>
  <a href="{SERVICE_URL}">Get your AI SEO strategy →</a>
</div>

<div class="foot">Generated by {AGENCY_NAME} · Platforms tested: {active_label}</div>
</div></body></html>"""
