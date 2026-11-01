#!/usr/bin/env python3
"""
Discovery: turn a single website URL into everything the checker needs.

One Claude call -> brand name, category, 5 bottom-of-funnel buyer queries, and
5 real competitors (name + domain). This is what makes the demo "one field in".
"""

import json
import os
import re
from pathlib import Path

import requests

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


def norm_domain(url):
    return (url.lower().replace("https://", "").replace("http://", "")
            .replace("www.", "").strip("/").split("/")[0])


def fetch_site_text(domain):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    parts = []
    for page in ["", "/about", "/pricing", "/product"]:
        try:
            r = requests.get(f"https://{domain}{page}", headers=headers, timeout=10)
            txt = re.sub(r"<[^>]+>", " ", r.text)
            txt = re.sub(r"\s+", " ", txt)
            parts.append(txt[:2000])
        except Exception:
            pass
    return "\n".join(parts)[:6000]


PROMPT = """You are an AEO/SEO analyst. From this company's website, return ONLY valid JSON.

Domain: {domain}
Website content:
{content}

Return exactly:
{{
  "brand": "official brand name",
  "category": "short category label",
  "keywords": ["5 bottom-of-funnel buyer queries — real buyer language, non-branded, the kind where being cited in an AI answer wins the deal"],
  "competitors": [{{"name": "Name", "domain": "domain.com"}}]
}}

Rules:
- exactly 5 keywords, bottom-of-funnel (comparison / 'best X for Y' / 'X alternatives' / 'top X tools')
- exactly 5 real direct competitors with real domains
- no branded queries (do not use this company's own name)"""


def _parse(text, domain):
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        text = m.group(1)
    data = json.loads(text)
    data["domain"] = domain
    data["keywords"] = data.get("keywords", [])[:5]
    data["competitors"] = data.get("competitors", [])[:5]
    return data


def _discover_claude(domain, content):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model="claude-opus-4-8", max_tokens=1500,
        messages=[{"role": "user", "content": PROMPT.format(domain=domain, content=content)}],
    )
    return _parse(resp.content[0].text.strip(), domain)


def _discover_gemini(domain, content):
    key = os.environ.get("GEMINI_API_KEY", "")
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={key}",
        json={"contents": [{"parts": [{"text": PROMPT.format(domain=domain, content=content)}]}],
              "generationConfig": {"responseMimeType": "application/json"}},
        timeout=60,
    )
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "gemini error"))
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _parse(text, domain)


def discover(url):
    """URL -> brand, domain, category, keywords[5], competitors[{name,domain}].

    Tries Claude, then Gemini, then a no-LLM heuristic — so the tool works on
    whichever key is funded (or none, in which case use --manual).
    """
    domain = norm_domain(url)
    content = fetch_site_text(domain)

    if ANTHROPIC_KEY and anthropic:
        try:
            return _discover_claude(domain, content)
        except Exception as e:
            print(f"  [discover] Claude failed ({str(e)[:60]}); trying Gemini…")

    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _discover_gemini(domain, content)
        except Exception as e:
            print(f"  [discover] Gemini failed ({str(e)[:60]}); using heuristic.")

    # Last-resort heuristic so nothing crashes (use --manual for real input)
    stem = domain.split(".")[0]
    return {
        "brand": stem.title(),
        "domain": domain,
        "category": "(unknown — no working LLM key; use --manual)",
        "keywords": [f"best {stem} alternative", f"top {stem} competitors"],
        "competitors": [],
    }


if __name__ == "__main__":
    import sys
    out = discover(sys.argv[1] if len(sys.argv) > 1 else "example.com")
    print(json.dumps(out, indent=2))
