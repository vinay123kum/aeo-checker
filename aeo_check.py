#!/usr/bin/env python3
"""
AEO Checker — core engine.

Given a brand (name + domain) and a list of buyer queries, checks whether the
brand is *cited* across 5 AI answer surfaces and returns a structured result
plus a single visibility score (0-10).

Platforms:
  google     Google AI Overview   -> SerpAPI  (live)
  bing       Bing / Copilot        -> SerpAPI  (live)
  claude     Claude (web search)   -> Anthropic API (live)
  perplexity Perplexity            -> Perplexity API (activates when key present)
  gemini     Gemini (grounding)    -> Gemini API     (activates when key present)

Each cell returns one of: "cited" | "not_cited" | "skipped" | "error".
Only platforms that actually ran (not skipped) count toward the score, so the
tool degrades gracefully when a key is missing.
"""

import json
import os
import re
from pathlib import Path

import requests

# Auto-load .env from this directory
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

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PERPLEXITY_KEY = os.environ.get("PERPLEXITY_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

# Bing is off by default: SerpAPI's Bing engine returns low-quality results
# (geo-defaults badly, only matches the first word) and Bing Copilot answers
# aren't exposed via API. Set ENABLE_BING=1 to include it as best-effort.
PLATFORMS = ["google", "perplexity", "claude", "gemini"]
if os.environ.get("ENABLE_BING") == "1":
    PLATFORMS.insert(2, "bing")
PLATFORM_NAMES = {
    "google": "Google AI Overview",
    "perplexity": "Perplexity",
    "bing": "Bing Copilot",
    "claude": "Claude",
    "gemini": "Gemini",
}


# ─── Brand matching ───────────────────────────────────────────────────────────

def _norm_domain(domain):
    return domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").strip("/").split("/")[0]


def is_cited(brand, domain, *blobs):
    """True if the brand domain or name appears in any of the text/url blobs."""
    d = _norm_domain(domain)
    name = brand.lower().strip()
    haystack = " ".join(b for b in blobs if b).lower()
    if d and d in haystack:
        return True
    # name match needs a word boundary to avoid false positives on short names
    if name and len(name) >= 3 and re.search(r"\b" + re.escape(name) + r"\b", haystack):
        return True
    return False


def _cell(status, sources=None, note=""):
    return {"status": status, "sources": sources or [], "note": note}


# ─── Google AI Overview (SerpAPI) ─────────────────────────────────────────────

def check_google(query, brand, domain):
    if not SERPAPI_KEY:
        return _cell("skipped", note="no SERPAPI_KEY")
    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": SERPAPI_KEY,
                    "hl": "en", "gl": "us"},
            timeout=30,
        )
        data = r.json()
        aio = data.get("ai_overview")
        if not aio:
            return _cell("not_cited", note="no AI Overview shown for this query")
        # Sometimes the AIO content lives behind a follow-up page_token call
        if aio.get("page_token") and not aio.get("text_blocks"):
            r2 = requests.get(
                "https://serpapi.com/search.json",
                params={"engine": "google_ai_overview", "page_token": aio["page_token"],
                        "api_key": SERPAPI_KEY},
                timeout=30,
            )
            aio = r2.json().get("ai_overview", aio)
        refs = aio.get("references", []) or []
        sources = [x.get("link") for x in refs if x.get("link")]
        blob = json.dumps(aio.get("text_blocks", [])) + " " + json.dumps(refs)
        cited = is_cited(brand, domain, blob, *sources)
        return _cell("cited" if cited else "not_cited", sources=sources[:8])
    except Exception as e:
        return _cell("error", note=str(e)[:120])


# ─── Bing (SerpAPI) ───────────────────────────────────────────────────────────

def check_bing(query, brand, domain):
    if not SERPAPI_KEY:
        return _cell("skipped", note="no SERPAPI_KEY")
    try:
        r = requests.get(
            "https://serpapi.com/search.json",
            params={"engine": "bing", "q": query, "api_key": SERPAPI_KEY, "cc": "us"},
            timeout=30,
        )
        data = r.json()
        organic = data.get("organic_results", []) or []
        # Bing Copilot answers aren't exposed via API; we scan the top answer
        # surfaces Bing does expose: answer box + top organic citations.
        answer = json.dumps(data.get("answer_box", {})) + json.dumps(data.get("knowledge_graph", {}))
        sources = [x.get("link") for x in organic[:6] if x.get("link")]
        blob = answer + " " + json.dumps([{"t": x.get("title"), "l": x.get("link")} for x in organic[:6]])
        cited = is_cited(brand, domain, blob, *sources)
        return _cell("cited" if cited else "not_cited", sources=sources[:6])
    except Exception as e:
        return _cell("error", note=str(e)[:120])


# ─── Claude (Anthropic web search) ────────────────────────────────────────────

def check_claude(query, brand, domain):
    if not (ANTHROPIC_KEY and anthropic):
        return _cell("skipped", note="no ANTHROPIC_API_KEY")
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        )
        sources, texts = [], []
        for block in resp.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                texts.append(getattr(block, "text", ""))
            elif btype == "web_search_tool_result":
                for item in getattr(block, "content", []) or []:
                    url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else None)
                    if url:
                        sources.append(url)
        cited = is_cited(brand, domain, " ".join(texts), *sources)
        return _cell("cited" if cited else "not_cited", sources=sources[:8])
    except Exception as e:
        return _cell("error", note=str(e)[:120])


# ─── Perplexity ───────────────────────────────────────────────────────────────

def check_perplexity(query, brand, domain):
    if not PERPLEXITY_KEY:
        return _cell("skipped", note="no PERPLEXITY_API_KEY")
    try:
        r = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {PERPLEXITY_KEY}"},
            json={"model": "sonar", "messages": [{"role": "user", "content": query}]},
            timeout=40,
        )
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        sources = data.get("citations", []) or [
            x.get("url") for x in data.get("search_results", []) if x.get("url")
        ]
        cited = is_cited(brand, domain, content, *sources)
        return _cell("cited" if cited else "not_cited", sources=sources[:8])
    except Exception as e:
        return _cell("error", note=str(e)[:120])


# ─── Gemini (Google Search grounding) ─────────────────────────────────────────

def check_gemini(query, brand, domain):
    if not GEMINI_KEY:
        return _cell("skipped", note="no GEMINI_API_KEY")
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_KEY}",
            json={"contents": [{"parts": [{"text": query}]}],
                  "tools": [{"google_search": {}}]},
            timeout=60,
        )
        data = r.json()
        if "error" in data:
            return _cell("error", note=str(data["error"].get("message", ""))[:120])
        cand = (data.get("candidates") or [{}])[0]
        text = json.dumps(cand.get("content", {}))
        gm = cand.get("groundingMetadata", {})
        chunks = gm.get("groundingChunks", []) or []
        titles = [c.get("web", {}).get("title", "") for c in chunks]
        sources = [c.get("web", {}).get("uri", "") for c in chunks if c.get("web", {}).get("uri")]
        blob = text + " " + " ".join(titles)
        cited = is_cited(brand, domain, blob, *titles)
        return _cell("cited" if cited else "not_cited", sources=sources[:8])
    except Exception as e:
        return _cell("error", note=str(e)[:120])


CHECKERS = {
    "google": check_google,
    "bing": check_bing,
    "claude": check_claude,
    "perplexity": check_perplexity,
    "gemini": check_gemini,
}


# ─── Orchestration + scoring ──────────────────────────────────────────────────

def run_company(brand, domain, queries, on_progress=None):
    """results[query][platform] = cell"""
    results = {}
    for q in queries:
        results[q] = {}
        for p in PLATFORMS:
            cell = CHECKERS[p](q, brand, domain)
            results[q][p] = cell
            if on_progress:
                on_progress(brand, q, p, cell["status"])
    return results


def score(results, queries):
    """Score = cited / (queries * active_platforms) * 10, ignoring skipped cells."""
    cited = possible = 0
    per_platform = {p: {"cited": 0, "ran": 0} for p in PLATFORMS}
    for q in queries:
        for p in PLATFORMS:
            st = results.get(q, {}).get(p, {}).get("status")
            # Only verdicts count. "error"/"skipped" mean we couldn't measure,
            # so they must not inflate the denominator and deflate the score.
            if st in ("cited", "not_cited"):
                possible += 1
                per_platform[p]["ran"] += 1
                if st == "cited":
                    cited += 1
                    per_platform[p]["cited"] += 1
    val = round((cited / possible) * 10, 1) if possible else 0.0
    return {"score": val, "cited": cited, "possible": possible, "per_platform": per_platform}


def active_platforms():
    """Which platforms have a key configured right now (no API calls)."""
    keys = {
        "google": SERPAPI_KEY,
        "bing": SERPAPI_KEY,
        "claude": ANTHROPIC_KEY and anthropic,
        "perplexity": PERPLEXITY_KEY,
        "gemini": GEMINI_KEY,
    }
    return [p for p in PLATFORMS if keys.get(p)]


if __name__ == "__main__":
    import sys
    brand = sys.argv[1] if len(sys.argv) > 1 else "Example"
    domain = sys.argv[2] if len(sys.argv) > 2 else "example.com"
    qs = ["best b2b saas marketing agency", "top demand generation agencies"]
    res = run_company(brand, domain, qs,
                      on_progress=lambda b, q, p, s: print(f"  [{p:10}] {s:10} {q[:40]}"))
    print(json.dumps(score(res, qs), indent=2))
