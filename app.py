"""
pulse. backend
--------------
A tiny Flask server that sits between your HTML frontend and NewsAPI.

Why this exists: NewsAPI's free plan only allows browser-side requests from
localhost, and even then it's a bad idea to ship an API key inside client-side
JavaScript (anyone can open devtools and copy it). So the browser talks to
this server, and this server is the only thing that ever sees the real key.

Run it:
    pip install -r requirements.txt
    python app.py
Then open pulse-news.html in your browser (or serve it) - it calls
http://localhost:5000/api/news
"""

import os
import re
import hashlib
from datetime import datetime, timezone

from flask import Flask, jsonify, request
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
NEWSAPI_BASE = "https://newsapi.org/v2"

# The frontend's category pills -> NewsAPI's top-headlines categories.
# NewsAPI doesn't have a "world" category, so we map it to "general".
CATEGORY_MAP = {
    "technology": "technology",
    "business": "business",
    "sports": "sports",
    "health": "health",
    "entertainment": "entertainment",
    "world": "general",
    "science": "science",
}

PLACEHOLDER_IMAGE = "https://images.unsplash.com/photo-1495020689067-958852a7765e?w=900&q=60"

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
def relative_time(published_at: str) -> str:
    if not published_at:
        return "just now"
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return "just now"
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
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
    source_name = (raw.get("source") or {}).get("name") or "Unknown"
    title = clean_title(raw.get("title") or "", source_name)
    description = (raw.get("description") or "").strip()

    content = (raw.get("content") or "").strip()
    # NewsAPI's free tier truncates content and appends "[+1234 chars]"
    content = re.sub(r"\[\+\d+ chars\]$", "", content).strip()

    # dedupe while preserving order (content sometimes just repeats description)
    seen = set()
    body = [p for p in [description, content] if p and not (p in seen or seen.add(p))]
    if not body:
        body = ["Full story available at the source link below."]

    return {
        "id": make_id(url),
        "cat": cat,
        "title": title,
        "excerpt": description or title,
        "source": source_name,
        "time": relative_time(raw.get("publishedAt") or ""),
        "image": raw.get("urlToImage") or PLACEHOLDER_IMAGE,
        "tags": guess_tags(title, description),
        "body": body,
        "hot": hot,
        "live": False,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/api/news")
def get_news():
    if not NEWSAPI_KEY:
        return jsonify({"error": "Server is missing NEWSAPI_KEY. Set it in .env."}), 500

    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "all").strip().lower()
    try:
        page_size = min(int(request.args.get("pageSize", 30)), 100)
    except ValueError:
        page_size = 30

    params = {"apiKey": NEWSAPI_KEY, "pageSize": page_size, "language": "en"}

    if q:
        # /everything is the right endpoint for free-text search
        endpoint = f"{NEWSAPI_BASE}/everything"
        params["q"] = q
        params["sortBy"] = "publishedAt"
    else:
        # /top-headlines for browsing by category (or the general front page)
        endpoint = f"{NEWSAPI_BASE}/top-headlines"
        params["country"] = "us"
        mapped = CATEGORY_MAP.get(category)
        if mapped:
            params["category"] = mapped

    try:
        r = requests.get(endpoint, params=params, timeout=10)
        data = r.json()
    except requests.RequestException as exc:
        return jsonify({"error": f"Could not reach NewsAPI: {exc}"}), 502

    if data.get("status") != "ok":
        return jsonify({"error": data.get("message", "NewsAPI returned an error")}), r.status_code

    raw_articles = [
        a for a in data.get("articles", [])
        if a.get("title") and a.get("title") != "[Removed]"
    ]

    fallback_cat = category if category in CATEGORY_MAP else "world"
    articles = [
        map_article(a, fallback_cat, hot=(i < 6))
        for i, a in enumerate(raw_articles)
    ]

    return jsonify({"status": "ok", "totalResults": len(articles), "articles": articles})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "hasKey": bool(NEWSAPI_KEY)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
