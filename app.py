"""
pulse. backend
--------------
A tiny Flask server that sits between your HTML frontend and Currents API
(https://currentsapi.services).

Why Currents instead of NewsAPI: NewsAPI's free "Developer" plan delays every
article by 24 hours by design (it's how they push people to the $449/mo paid
plan) - that's why the site kept showing "1d ago" no matter what. Currents'
free plan (250 requests/day, no credit card) has no such delay, so "Live
updates" can actually be live.

This server is the only thing that ever sees the real API key - the browser
never gets it directly.

Run it:
    pip install -r requirements.txt
    python app.py
Then open index.html in your browser (or serve it) - it calls
http://localhost:5000/api/news
"""

import os
import re
import hashlib
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

CURRENTS_API_KEY = os.environ.get("CURRENTS_API_KEY", "")
CURRENTS_BASE = "https://api.currentsapi.services/v1"

# The frontend's category pills -> Currents' legacy (v1) category values.
# Currents doesn't have a "world" category, so we map it to "general".
CATEGORY_MAP = {
    "technology": "technology",
    "business": "business",
    "sports": "sports",
    "health": "health",
    "entertainment": "entertainment",
    "world": "general",
    "science": "science",
}

STOPWORDS = {
    "this", "that", "with", "from", "have", "their", "they", "after", "will",
    "been", "were", "said", "also", "into", "more", "than", "when", "what",
    "which", "your", "about", "over", "amid", "says", "could", "would",
}


# ---------------------------------------------------------------------------
# Manual CORS (no flask-cors dependency needed)
# ---------------------------------------------------------------------------
@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_published(raw: str):
    """Currents timestamps look like '2026-08-23 14:05:00 +0000' (a space,
    not a 'T'), which datetime.fromisoformat() can't parse directly. Try a
    couple of shapes before giving up."""
    if not raw:
        return None
    raw = raw.strip()
    candidates = [raw]
    if " " in raw and "T" not in raw:
        candidates.append(raw.replace(" ", "T", 1))
    for candidate in candidates:
        try:
            dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def relative_time(dt) -> str:
    if not dt:
        return "just now"
    seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def make_id(url: str) -> int:
    """Stable numeric id derived from the article URL, so the same story
    gets the same id across requests (bookmarking, #article-<id> links)."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return int(digest, 16) % (2 ** 31)


def guess_tags(title: str, description: str):
    text = f"{title} {description or ''}".lower()
    words = re.findall(r"[a-z]{4,}", text)
    tags = []
    for w in words:
        if w in STOPWORDS or w in tags:
            continue
        tags.append(w)
        if len(tags) >= 5:
            break
    return tags


def clean_title(title: str, source_name: str) -> str:
    suffix = f" - {source_name}"
    if title and title.endswith(suffix):
        return title[: -len(suffix)].strip()
    return (title or "Untitled").strip()


def map_article(raw: dict, cat: str, hot: bool = False):
    url = raw.get("url") or ""
    # Currents doesn't give a clean "source name" field like NewsAPI did -
    # fall back to the domain out of the URL.
    source_name = "Unknown"
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    if m:
        source_name = m.group(1)

    title = clean_title(raw.get("title") or "", source_name)
    description = (raw.get("description") or "").strip()
    body = [description] if description else ["Full story available at the source link below."]

    published_dt = parse_published(raw.get("published") or "")

    # Currents sometimes literally returns the string "None" instead of a
    # real null when there's no image - guard against that.
    image = raw.get("image") or ""
    if image in ("None", "null"):
        image = ""

    return {
        "id": make_id(url),
        "cat": cat,
        "title": title,
        "excerpt": description or title,
        "source": source_name,
        "time": relative_time(published_dt),
        # Raw timestamp, passed through so the frontend can sort by actual
        # recency (e.g. picking the newest items for "Live updates").
        "publishedAt": published_dt.isoformat() if published_dt else "",
        "image": image,
        "tags": guess_tags(title, description),
        "body": body,
        "hot": hot,
        "live": False,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/api/news")
def get_news():
    if not CURRENTS_API_KEY:
        return jsonify({"error": "Server is missing CURRENTS_API_KEY. Set it in .env."}), 500

    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "all").strip().lower()
    try:
        page_size = min(int(request.args.get("pageSize", 30)), 100)
    except ValueError:
        page_size = 30

    headers = {
    "Authorization": f"Bearer {CURRENTS_API_KEY}",
    "Accept": "application/json",
    "User-Agent": "pulse-news-app/1.0",
    }

    params = {
        "language": "en",
        "page_size": page_size,
    }

    if q:
        # /search is the right endpoint for free-text queries. `limit` is
        # only honoured on /search, not on /latest-news.
        endpoint = f"{CURRENTS_BASE}/search"
        params["keywords"] = q
        params["page_size"] = page_size
    else:
        # /latest-news for browsing by category (or the general front page).
        endpoint = f"{CURRENTS_BASE}/latest-news"
        params["country"] = "US"
        mapped = CATEGORY_MAP.get(category)
        if mapped:
            params["category"] = mapped

    # Currents occasionally takes a while to respond (more so right after
    # this server itself wakes up from Render's free-tier sleep, when the
    # first outbound request pays a cold DNS/TLS cost). One slow response
    # used to surface immediately as "Could not reach Currents API" with a
    # ReadTimeout. Retry once with a longer timeout before giving up.
    data = None
    r = None
    last_exc = None
    for attempt, timeout in enumerate((10, 20), start=1):
        try:
            r = requests.get(endpoint, headers=headers, params=params, timeout=timeout)
            data = r.json()
            break
        except requests.RequestException as exc:
            last_exc = exc
            print(f"[news] attempt {attempt} failed ({timeout}s timeout): {exc}")
        except ValueError:
            print(
                f"[news] Non-JSON response from Currents: "
                f"status={r.status_code}, "
                f"content_type={r.headers.get('content-type')}, "
                f"body={r.text[:500]}"
            )
            return jsonify({
                "error": "Currents API returned a non-JSON response",
                "status": r.status_code
            }), 502

    if data is None:
        return jsonify({"error": f"Could not reach Currents API: {last_exc}"}), 502

    # DEBUG: if two different categories are returning the same articles,
    # check the Render logs for this line. Compare the "params" and the
    # first couple of "titles" across two requests (e.g. ?category=technology
    # vs ?category=health). If params differ but titles are identical, the
    # problem is upstream (Currents isn't honoring `category` for this plan/
    # combination) rather than in this backend. Remove once diagnosed.
    print(
        f"[news] endpoint={endpoint} params={params} "
        f"returned={len(data.get('news', []))} "
        f"titles={[a.get('title') for a in data.get('news', [])[:3]]}"
    )

    if data.get("status") != "ok":
        message = (
            data.get("message")
            or data.get("error")
            or "Currents API returned an error"
        )

        status_code = 502
        if r is not None:
            status_code = r.status_code if r.status_code >= 400 else 502

        return jsonify({"error": message}), status_code

    raw_articles = [
        a for a in data.get("news", [])
        if a.get("title") and a.get("title") != "[Removed]"
    ]

    # Always sort newest-first ourselves - don't assume the API's own
    # ordering matches actual publish time.
    raw_articles.sort(
        key=lambda a: parse_published(a.get("published") or "") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    fallback_cat = category if category in CATEGORY_MAP else "world"
    articles = [
        map_article(a, fallback_cat, hot=(i < 6))
        for i, a in enumerate(raw_articles[:page_size])
    ]

    return jsonify({"status": "ok", "totalResults": len(articles), "articles": articles})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "hasKey": bool(CURRENTS_API_KEY)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
