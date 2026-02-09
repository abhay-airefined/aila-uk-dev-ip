import requests
import json
import re
from urllib.parse import quote_plus
from typing import List, Dict, Optional

# -----------------------------
# Configuration
# -----------------------------

SOURCE_WEIGHTS = {
    "Open Library": 1.0,
    "Google Books": 1.0,
    "British Library": 1.0,
    "Library of Congress": 1.0,
    "LibGen": 1.0,        # risk signal only
    "Z-Library": 1.0     # risk signal only
}

MIN_RAW_SIMILARITY = 30
REQUEST_TIMEOUT = 10

LIBGEN_MIRRORS = [
    "https://libgen.li/index.php?req={q}&res=25",
    "https://libgen.rs/search.php?req={q}",
    "https://libgen.is/search.php?req={q}",
]

# -----------------------------
# Utilities
# -----------------------------

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower())

def token_similarity(a: str, b: str) -> float:
    a_tokens = set(normalize(a).split())
    b_tokens = set(normalize(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    return round((len(a_tokens & b_tokens) / len(a_tokens | b_tokens)) * 100, 2)

def safe_get(url: str) -> Optional[dict]:
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

# -----------------------------
# Source Fetchers (metadata only)
# -----------------------------

def fetch_open_library(title=None, author=None, isbn=None):
    params = []
    if title:
        params.append(f"title={quote_plus(title)}")
    if author:
        params.append(f"author={quote_plus(author)}")
    if isbn:
        params.append(f"isbn={quote_plus(isbn)}")

    url = f"https://openlibrary.org/search.json?{'&'.join(params)}"
    data = safe_get(url)
    if not data:
        return []

    results = []
    for d in data.get("docs", [])[:15]:
        results.append({
            "source": "Open Library",
            "title": d.get("title"),
            "author": ", ".join(d.get("author_name", [])) if d.get("author_name") else None,
            "isbn": d.get("isbn", [None])[0],
            "url": f"https://openlibrary.org{d.get('key')}",
            "link_type": "catalog_record"
        })
    return results

def fetch_google_books(title=None, author=None, isbn=None):
    q = []
    if title:
        q.append(f"intitle:{title}")
    if author:
        q.append(f"inauthor:{author}")
    if isbn:
        q.append(f"isbn:{isbn}")

    url = f"https://www.googleapis.com/books/v1/volumes?q={quote_plus(' '.join(q))}"
    data = safe_get(url)
    if not data:
        return []

    results = []
    for item in data.get("items", [])[:15]:
        v = item.get("volumeInfo", {})
        results.append({
            "source": "Google Books",
            "title": v.get("title"),
            "author": ", ".join(v.get("authors", [])) if v.get("authors") else None,
            "isbn": (v.get("industryIdentifiers") or [{}])[0].get("identifier"),
            "url": v.get("infoLink"),
            "link_type": "preview_page"
        })
    return results

def fetch_british_library(title=None, author=None):
    q = " ".join(filter(None, [title, author]))
    if not q:
        return []

    return [{
        "source": "British Library",
        "title": title,
        "author": author,
        "isbn": None,
        "url": f"https://explore.bl.uk/search?q={quote_plus(q)}",
        "link_type": "catalog_search"
    }]

def fetch_loc(title=None, author=None):
    q = " ".join(filter(None, [title, author]))
    if not q:
        return []

    url = f"https://www.loc.gov/books/?q={quote_plus(q)}&fo=json"
    data = safe_get(url)
    if not data:
        return []

    results = []
    for r in data.get("results", [])[:15]:
        results.append({
            "source": "Library of Congress",
            "title": r.get("title"),
            "author": r.get("creator"),
            "isbn": None,
            "url": r.get("url"),
            "link_type": "catalog_record"
        })
    return results

def fetch_shadow_sources(title=None, author=None, isbn=None):
    q = title or author or isbn
    if not q:
        return []

    encoded = quote_plus(q)
    results = []

    for mirror in LIBGEN_MIRRORS:
        results.append({
            "source": "LibGen",
            "title": title,
            "author": author,
            "isbn": isbn,
            "url": mirror.format(q=encoded),
            "link_type": "search_page",
            "legal_note": "High-risk shadow library (search page only)"
        })

    results.append({
        "source": "Z-Library",
        "title": title,
        "author": author,
        "isbn": isbn,
        "url": f"https://z-library.se/s/{encoded}",
        "link_type": "search_page",
        "legal_note": "High-risk shadow library (search page only)"
    })

    return results

# -----------------------------
# Scoring + Classification
# -----------------------------

def score_results(title, results, isbn=None, author=None):
    scored = []

    for r in results:
        # ISBN = exact match signal
        if isbn and r.get("isbn") == isbn:
            raw = 100.0

        # Title similarity
        elif title:
            raw = token_similarity(title, r.get("title") or "")

        # Author-only fallback
        elif author and author.lower() in (r.get("author") or "").lower():
            raw = 70.0

        else:
            raw = 0.0

        if raw < MIN_RAW_SIMILARITY:
            continue

        weight = SOURCE_WEIGHTS.get(r["source"], 0.5)
        scored.append({
            **r,
            "raw_score": raw,
            "weighted_score": round(raw * weight, 2)
        })

    return scored

def classify(scored):
    legit, alternate, risky, noise = [], [], [], []

    for r in scored:
        src = r["source"]
        raw = r["raw_score"]

        if src in ["LibGen", "Z-Library"] and raw >= 60:
            risky.append(r)
        elif raw >= 85 and src not in ["LibGen", "Z-Library"]:
            legit.append(r)
        elif raw >= 60:
            alternate.append(r)
        else:
            noise.append(r)

    return legit, alternate, risky, noise

# -----------------------------
# Legal Evidence JSON
# -----------------------------

def generate_legal_evidence(query, legit, alternate, risky):
    return {
        "queried_metadata": query,
        "assessment_type": "Copyright availability & infringement risk",
        "legitimate_availability": legit,
        "alternate_legitimate_editions": alternate,
        "high_risk_distribution_signals": risky,
        "risk_summary": {
            "legitimate_sources_detected": len(legit),
            "shadow_library_signals": len(risky),
            "overall_risk_level": "HIGH" if risky else "LOW"
        }
    }

# -----------------------------
# Pipeline Runner (API-safe)
# -----------------------------

def run_pipeline(title=None, author=None, isbn=None):
    all_results = []
    all_results += fetch_open_library(title, author, isbn)
    all_results += fetch_google_books(title, author, isbn)
    all_results += fetch_british_library(title, author)
    all_results += fetch_loc(title, author)
    all_results += fetch_shadow_sources(title, author, isbn)

    scored = score_results(title, all_results, isbn, author)
    legit, alternate, risky, noise = classify(scored)

    evidence = generate_legal_evidence(
        {"title": title, "author": author, "isbn": isbn},
        legit, alternate, risky
    )

    return {
        "evidence": evidence,
        "scored_matches": scored,
        "legitimate_availability": legit,
        "alternate_legitimate_editions": alternate,
        "high_risk_distribution_signals": risky,
        "noise": noise
    }

# -----------------------------
# CLI Test Harness
# -----------------------------

if __name__ == "__main__":
    print("\n🔍 IP Metadata Search Test\n")

    title = input("Title (optional): ").strip() or None
    author = input("Author (optional): ").strip() or None
    isbn = input("ISBN (optional): ").strip() or None

    output = run_pipeline(title, author, isbn)

    print("\n📊 Results:")
    print(json.dumps(output["evidence"], indent=2))

    with open("legal_evidence.json", "w", encoding="utf-8") as f:
        json.dump(output["evidence"], f, indent=2)

    print("\n✅ Test completed — legal_evidence.json generated")
