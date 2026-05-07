# HoruScope

Midwest wage and hour enforcement intelligence pipeline.

Live interface: [https://uhq-actual.github.io/HoruScope/](https://uhq-actual.github.io/HoruScope/)

## Quick Start

```bash
python -m pip install -r requirements.txt
python -m unittest discover
python wage_news_pipeline.py all --days 7 --out brief.md
python wage_news_pipeline.py site-data --days 7 --out stories.json
```

The default SQLite database is `wage_news.db`. Set `WAGE_DB` to use another path.

## Commands

```bash
python wage_news_pipeline.py collect
python wage_news_pipeline.py trends
python wage_news_pipeline.py digest --days 7 --out brief.md
python wage_news_pipeline.py all --days 7 --out brief.md
python wage_news_pipeline.py site-data --days 7 --out stories.json
```

## Inputs

- RSS: DOL national releases feed.
- GDELT DOC 2.0: free article search using wage and hour terms plus Midwest state and metro cues.
- NewsAPI: optional; set `NEWSAPI_KEY` in `.env` and pass `--newsapi`.
- BLS LASST: state unemployment-rate series for IL, IN, IA, KS, MI, MN, MO, NE, OH, and WI.

## API Limits and Keys

- BLS Public Data API has a maximum of 50 time series per request and 500 daily queries for registered v2 usage. The script sends 10 LASST series in one POST. `BLS_API_KEY` is optional for basic use but recommended.
- GDELT DOC 2.0 requires no key. Keep `--maxrecords` conservative for routine runs.
- NewsAPI requires `NEWSAPI_KEY`; the collector skips NewsAPI when the key is missing unless you explicitly enable it.

## Output

`digest` and `all` emit markdown with:

- Top enforcement items
- Labor trend signals
- Watchlist
- Analyst synthesis when the item set supports it

Each item includes Where, Topic, Source with date, Score, Snippet, and Link.

`site-data` writes `stories.json` for the GitHub Pages interface. If the current database window has no scored Midwest items, it fills the page from a curated official DOL Midwest case library. Pass `--no-curated` to render the empty state instead.

## Deployment

Use WSL2 plus cron first. Move to a small VPS with systemd timers when you need always-on delivery.
