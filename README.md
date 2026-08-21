# pulse.

A live news search and browsing app. Type a topic or pick a category, and it pulls real, current headlines from [NewsAPI](https://newsapi.org).

**Live demo:** https://pulse-news-website.onrender.com _(backend health check — the actual site is `pulse-news.html`, opened locally or hosted separately)_

## How it works

- **Frontend** (`pulse-news.html`) — a single-page HTML/CSS/JS interface: search bar, category pills, a hero carousel for top stories, a live-updating feed, and full article pages.
- **Backend** (`app.py`) — a small Flask server that proxies requests to NewsAPI. It keeps the API key server-side (never exposed to the browser) and reshapes NewsAPI's response into the format the frontend expects.

The frontend never talks to NewsAPI directly — every search and category click goes through the Flask backend first.

## Running it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open `pulse-news.html` in a browser. Make sure a `.env` file sits next to `app.py` with:

```
NEWSAPI_KEY=your_key_here
```

(Get a free key at [newsapi.org](https://newsapi.org).)

## Deployment

The backend is deployed on [Render](https://render.com) (free tier) with `NEWSAPI_KEY` set as an environment variable. The frontend's `BACKEND_URL` constant points to that live Render URL.

## Tech

Flask, Python, vanilla JavaScript/HTML/CSS, NewsAPI.
