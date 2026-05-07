# HoruScope Development Guidelines

## Project Overview

HoruScope is a Midwest wage and hour news intelligence pipeline for surfacing enforcement leads and labor signals across IL, IN, IA, KS, MI, MN, MO, NE, OH, and WI.

## Ground Rules

- Treat the project as an enforcement pipeline, not a generic news feed.
- Every artifact should answer: what happened, where, implicated statute or wage theory, industry, pattern signal, targeting lead value, and what to watch next.
- Distinguish official enforcement actions from press coverage. A consent judgment, civil money penalty, or debarment outranks a news writeup of the same event.
- Secrets live in `.env`; never commit keys or credentials.
- Use relative paths or environment variables in code and docs.
- Use the TrueCrimeAudit git identity for commits.

## Development Commands

```bash
python -m pip install -r requirements.txt
python -m unittest discover
python wage_news_pipeline.py collect
python wage_news_pipeline.py trends
python wage_news_pipeline.py digest --days 7 --out brief.md
python wage_news_pipeline.py all --days 7 --out brief.md
```

## Pipeline Contract

1. Collector: RSS via `feedparser`, HTTP via `requests`, GDELT DOC 2.0, optional NewsAPI, and SQLite storage at `wage_news.db`.
2. Classifier: wage and hour terms, statutes, vulnerable sectors, official-source flags, and concrete Midwest geography.
3. Geography filter: keep items with a Midwest state, state code, or major metro cue. Do not keep an item on regional phrasing alone.
4. Scorer: official source, wage violation language, Midwest geography, vulnerable sector, trend tie-in, and generic-market-noise penalty.
5. Digest: markdown sections for top enforcement items, labor trend signals, watchlist, and optional synthesis.

## Source Notes

- DOL RSS source: `https://www.dol.gov/rss/releases.xml`.
- GDELT DOC 2.0 is free and does not use a local key here.
- NewsAPI is optional and requires `NEWSAPI_KEY`.
- BLS Public Data API is used for LASST unemployment trend rows. `BLS_API_KEY` is optional for basic use but recommended for registered v2 usage and rate-limit headroom.
