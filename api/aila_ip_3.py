# import requests
# import json
# import re
# from collections import Counter

# # -----------------------------
# # Configuration
# # -----------------------------

# SOURCE_WEIGHTS = {
#     "Open Library": 1.0,
#     "Google Books": 1.0,
#     "British Library": 0.9,
#     "Library of Congress": 0.9,
#     "LibGen": 0.4,
#     "Z-Library": 1.0
# }

# MIN_RAW_SIMILARITY = 30

# # -----------------------------
# # Utilities
# # -----------------------------

# def normalize(text):
#     return re.sub(r"[^a-z0-9 ]", "", text.lower())

# def token_similarity(a, b):
#     a_tokens = set(normalize(a).split())
#     b_tokens = set(normalize(b).split())
#     if not a_tokens or not b_tokens:
#         return 0.0
#     return round((len(a_tokens & b_tokens) / len(a_tokens | b_tokens)) * 100, 2)

# # -----------------------------
# # Source Fetchers (metadata only)
# # -----------------------------

# def fetch_open_library(title):
#     url = f"https://openlibrary.org/search.json?title={title}"
#     data = requests.get(url, timeout=10).json()
#     results = []
#     for d in data.get("docs", [])[:15]:
#         results.append({
#             "source": "Open Library",
#             "title": d.get("title"),
#             "url": f"https://openlibrary.org{d.get('key')}"
#         })
#     return results

# def fetch_google_books(title):
#     url = f"https://www.googleapis.com/books/v1/volumes?q=intitle:{title}"
#     data = requests.get(url, timeout=10).json()
#     results = []
#     for item in data.get("items", [])[:15]:
#         v = item["volumeInfo"]
#         results.append({
#             "source": "Google Books",
#             "title": v.get("title"),
#             "url": v.get("infoLink")
#         })
#     return results

# def fetch_british_library(title):
#     return [{
#         "source": "British Library",
#         "title": title.lower(),
#         "url": f"https://explore.bl.uk/search?q={title.replace(' ', '+')}"
#     }]

# def fetch_loc(title):
#     url = f"https://www.loc.gov/books/?q={title}&fo=json"
#     data = requests.get(url, timeout=10).json()
#     results = []
#     for r in data.get("results", [])[:20]:
#         results.append({
#             "source": "Library of Congress",
#             "title": r.get("title"),
#             "url": r.get("url")
#         })
#     return results

# def fetch_shadow_sources(title):
#     return [
#         {"source": "LibGen", "title": title.lower(), "url": "https://libgen.rs/"},
#         {"source": "Z-Library", "title": title.lower(), "url": "https://z-library.se/"}
#     ]

# # -----------------------------
# # Scoring + Classification
# # -----------------------------

# def score_results(query, results):
#     scored = []
#     for r in results:
#         raw = token_similarity(query, r["title"] or "")
#         if raw < MIN_RAW_SIMILARITY:
#             continue

#         weight = SOURCE_WEIGHTS.get(r["source"], 0.5)
#         scored.append({
#             **r,
#             "raw_score": raw,
#             "weighted_score": round(raw * weight, 2)
#         })
#     return scored

# def classify(scored):
#     legit, alternate, risky, noise = [], [], [], []

#     for r in scored:
#         src = r["source"]
#         raw = r["raw_score"]

#         if src in ["LibGen", "Z-Library"] and raw >= 60:
#             risky.append(r)

#         elif raw >= 85 and src in SOURCE_WEIGHTS and src not in ["LibGen", "Z-Library"]:
#             legit.append(r)

#         elif raw >= 60 and src not in ["LibGen", "Z-Library"]:
#             alternate.append(r)

#         else:
#             noise.append(r)

#     return legit, alternate, risky, noise

# # -----------------------------
# # Legal Evidence JSON
# # -----------------------------

# def generate_legal_evidence(query, legit, alternate, risky):
#     return {
#         "queried_title": query,
#         "assessment_type": "Copyright availability & infringement risk",
#         "legitimate_availability": legit,
#         "alternate_legitimate_editions": alternate,
#         "high_risk_distribution_signals": risky,
#         "risk_summary": {
#             "legitimate_sources_detected": len(legit),
#             "shadow_library_signals": len(risky),
#             "overall_risk_level": (
#                 "HIGH" if risky else "LOW"
#             )
#         }
#     }

# # -----------------------------
# # Main
# # -----------------------------

# def main():
#     # backward-compatible CLI behaviour (keeps original behaviour)
#     query = input("Enter book title: ").strip()
#     out = run_pipeline(query)

#     evidence = out.get("evidence")
#     legit = out.get("legitimate_availability", [])
#     alternate = out.get("alternate_legitimate_editions", [])
#     risky = out.get("high_risk_distribution_signals", [])

#     print("\n📌 Legitimate availability:")
#     for r in legit:
#         print(f"[{r.get('weighted_score')}] {r.get('source')} | {r.get('title')} | {r.get('url')}")

#     print("\n📚 Alternate legitimate editions:")
#     for r in alternate:
#         print(f"[{r.get('weighted_score')}] {r.get('source')} | {r.get('title')} | {r.get('url')}")

#     print("\n🚨 High-risk distribution signals:")
#     for r in risky:
#         print(f"[{r.get('weighted_score')}] {r.get('source')} | {r.get('title')} | {r.get('url')}")

#     with open("legal_evidence.json", "w", encoding="utf-8") as f:
#         json.dump(evidence, f, indent=2)

#     print("\n✅ Legal-ready evidence JSON generated: legal_evidence.json")

# if __name__ == "__main__":
#     main()


# def run_pipeline(query: str):
#     """Programmatic runner for the aila_ip_3 pipeline.

#     Returns a dictionary suitable for JSON responses from an API.
#     """
#     if not query:
#         return {"error": "empty query"}

#     all_results = []
#     all_results += fetch_open_library(query)
#     all_results += fetch_google_books(query)
#     all_results += fetch_british_library(query)
#     all_results += fetch_loc(query)
#     all_results += fetch_shadow_sources(query)

#     scored = score_results(query, all_results)
#     legit, alternate, risky, noise = classify(scored)

#     evidence = generate_legal_evidence(query, legit, alternate, risky)

#     return {
#         "queried_title": query,
#         "evidence": evidence,
#         "scored_matches": scored,
#         "legitimate_availability": legit,
#         "alternate_legitimate_editions": alternate,
#         "high_risk_distribution_signals": risky,
#         "noise": noise,
#     }




import requests
import json
import re
from urllib.parse import quote_plus

# -----------------------------
# Configuration
# -----------------------------

SOURCE_WEIGHTS = {
    "Open Library": 1.0,
    "Google Books": 1.0,
    "British Library": 0.9,
    "Library of Congress": 0.9,
    "LibGen": 0.4,          # intentionally low (risk signal only)
    "Z-Library": 0.4        # intentionally low (risk signal only)
}

MIN_RAW_SIMILARITY = 30

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

# -----------------------------
# Source Fetchers (metadata only)
# -----------------------------

def fetch_open_library(title):
    url = f"https://openlibrary.org/search.json?title={quote_plus(title)}"
    data = requests.get(url, timeout=10).json()
    results = []

    for d in data.get("docs", [])[:15]:
        results.append({
            "source": "Open Library",
            "title": d.get("title"),
            "url": f"https://openlibrary.org{d.get('key')}",
            "link_type": "catalog_record"
        })
    return results

def fetch_google_books(title):
    url = f"https://www.googleapis.com/books/v1/volumes?q=intitle:{quote_plus(title)}"
    data = requests.get(url, timeout=10).json()
    results = []

    for item in data.get("items", [])[:15]:
        v = item.get("volumeInfo", {})
        results.append({
            "source": "Google Books",
            "title": v.get("title"),
            "url": v.get("infoLink"),
            "link_type": "preview_page"
        })
    return results

def fetch_british_library(title):
    return [{
        "source": "British Library",
        "title": title,
        "url": f"https://explore.bl.uk/search?q={quote_plus(title)}",
        "link_type": "catalog_search"
    }]

def fetch_loc(title):
    url = f"https://www.loc.gov/books/?q={quote_plus(title)}&fo=json"
    data = requests.get(url, timeout=10).json()
    results = []

    for r in data.get("results", [])[:20]:
        results.append({
            "source": "Library of Congress",
            "title": r.get("title"),
            "url": r.get("url"),
            "link_type": "catalog_record"
        })
    return results

def fetch_libgen(title):
    encoded = quote_plus(title)
    results = []

    for mirror in LIBGEN_MIRRORS:
        results.append({
            "source": "LibGen",
            "title": title,
            "url": mirror.format(q=encoded),
            "link_type": "search_page",
            "legal_note": "High-risk shadow library. Search page only."
        })

    return results

def fetch_zlibrary(title):
    return [{
        "source": "Z-Library",
        "title": title,
        "url": f"https://z-library.se/s/{quote_plus(title)}",
        "link_type": "search_page",
        "legal_note": "High-risk shadow library. Search page only."
    }]

def fetch_shadow_sources(title):
    results = []
    results.extend(fetch_libgen(title))
    results.extend(fetch_zlibrary(title))
    return results

# -----------------------------
# Scoring + Classification
# -----------------------------

def score_results(query, results):
    scored = []

    for r in results:
        raw = token_similarity(query, r.get("title") or "")
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

        elif raw >= 60 and src not in ["LibGen", "Z-Library"]:
            alternate.append(r)

        else:
            noise.append(r)

    return legit, alternate, risky, noise

# -----------------------------
# Legal Evidence JSON
# -----------------------------

def generate_legal_evidence(query, legit, alternate, risky):
    return {
        "queried_title": query,
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

def run_pipeline(query: str):
    if not query:
        return {"error": "empty query"}

    all_results = []
    all_results += fetch_open_library(query)
    all_results += fetch_google_books(query)
    all_results += fetch_british_library(query)
    all_results += fetch_loc(query)
    all_results += fetch_shadow_sources(query)

    scored = score_results(query, all_results)
    legit, alternate, risky, noise = classify(scored)

    evidence = generate_legal_evidence(query, legit, alternate, risky)

    return {
        "queried_title": query,
        "evidence": evidence,
        "scored_matches": scored,
        "legitimate_availability": legit,
        "alternate_legitimate_editions": alternate,
        "high_risk_distribution_signals": risky,
        "noise": noise
    }

# -----------------------------
# CLI (optional, safe)
# -----------------------------

if __name__ == "__main__":
    query = input("Enter book title: ").strip()
    output = run_pipeline(query)

    with open("legal_evidence.json", "w", encoding="utf-8") as f:
        json.dump(output.get("evidence"), f, indent=2)

    print("✅ Legal-ready evidence JSON generated: legal_evidence.json")
