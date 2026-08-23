# pulse.

A live news search and browsing app. Type a topic or pick a category, and it pulls real, current headlines from [Currents API](https://currentsapi.services).

**Live demo:** https://pulse-news-website.onrender.com _(backend health check — the actual site is `index.html`, opened locally or hosted separately)_

## How it works

- **Frontend** (`index.html`) — a single-page HTML/CSS/JS interface: search bar, category pills, a hero carousel for top stories, a live-updating feed, and full article pages.
- **Backend** (`app.py`) — a small Flask server that proxies requests to Currents API. It keeps the API key server-side (never exposed to the browser) and reshapes Currents' response into the format the frontend expects.

The frontend never talks to Currents API directly — every search and category click goes through the Flask backend first.

### Why Currents instead of NewsAPI

NewsAPI's free "Developer" plan delays every article by 24 hours by design (it's how they push people to the $449/mo paid plan) — that's why the site used to show "1d ago" no matter what. Currents' free plan (250 requests/day, no credit card) has no such delay, so "Live updates" can actually be live.

## Running it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open `index.html` in a browser. Make sure a `.env` file sits next to `app.py` with:

```
CURRENTS_API_KEY=your_key_here
```

(Get a free key at [currentsapi.services](https://currentsapi.services).)

## Deployment

The backend is deployed on [Render](https://render.com) (free tier) with `CURRENTS_API_KEY` set as an environment variable. The frontend's `BACKEND_URL` constant points to that live Render URL.

## Tech

Flask, Python, vanilla JavaScript/HTML/CSS, Currents API.
