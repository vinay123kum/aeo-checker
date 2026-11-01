#!/usr/bin/env python3
"""
AEO Checker — CLI.

  python run.py example.com
  python run.py example.com --out report.html

One URL in -> discovers brand/keywords/competitors -> checks AI visibility across
every platform with a configured key -> writes a styled HTML report.
"""

import argparse
from pathlib import Path

import aeo_check
import discover as disc
import report as rep


def build(url, out_path=None, on_progress=None, manual=None):
    # manual = {"brand","domain","keywords":[...],"competitors":[{"name","domain"}]}
    # lets the tool run end-to-end without an LLM discovery key.
    d = manual or disc.discover(url)
    platforms = aeo_check.active_platforms()
    if not platforms:
        raise SystemExit("No platform keys configured. Add SERPAPI_KEY / ANTHROPIC_API_KEY to .env")

    queries = d["keywords"]

    def progress(brand, q, p, status):
        if on_progress:
            on_progress(brand, q, p, status)
        else:
            print(f"  [{p:10}] {status:10} {brand[:22]:<22} {q[:38]}")

    print(f"\nProspect: {d['brand']} ({d['domain']})  |  platforms: {', '.join(platforms)}")
    prospect = {"brand": d["brand"], "domain": d["domain"]}
    prospect["results"] = aeo_check.run_company(d["brand"], d["domain"], queries, progress)
    prospect["score"] = aeo_check.score(prospect["results"], queries)["score"]

    competitors = []
    for c in d["competitors"]:
        print(f"\nCompetitor: {c['name']} ({c['domain']})")
        res = aeo_check.run_company(c["name"], c["domain"], queries, progress)
        competitors.append({"brand": c["name"], "domain": c["domain"],
                            "results": res,
                            "score": aeo_check.score(res, queries)["score"]})

    h = rep.render(prospect, competitors, queries, None, platforms)
    out = Path(out_path or f"report_{d['domain'].replace('.', '_')}.html")
    out.write_text(h, encoding="utf-8")
    print(f"\n[DONE] {prospect['brand']} scored {prospect['score']}/10")
    print(f"Report: {out.resolve()}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="website URL or domain")
    ap.add_argument("--out", help="output HTML path")
    ap.add_argument("--manual", help="JSON file with brand/domain/keywords/competitors (skips LLM discovery)")
    args = ap.parse_args()
    manual = None
    if args.manual:
        import json
        manual = json.loads(Path(args.manual).read_text())
        manual.setdefault("domain", disc.norm_domain(args.url))
    build(args.url, args.out, manual=manual)
