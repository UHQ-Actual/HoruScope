"""Midwest wage and hour news intelligence pipeline."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import sqlite3
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

try:
    import feedparser  # type: ignore
except ImportError:  # pragma: no cover - exercised by collector command
    feedparser = None

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover - exercised by network commands
    requests = None


DB_ENV = "WAGE_DB"
DEFAULT_DB = "wage_news.db"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_API = "https://newsapi.org/v2/everything"

MIDWEST_STATES: dict[str, dict[str, Any]] = {
    "IL": {"name": "Illinois", "fips": "17", "metros": ["Chicago", "Peoria", "Rockford", "Springfield"]},
    "IN": {"name": "Indiana", "fips": "18", "metros": ["Indianapolis", "Fort Wayne", "South Bend", "Evansville"]},
    "IA": {"name": "Iowa", "fips": "19", "metros": ["Des Moines", "Cedar Rapids", "Davenport", "Sioux City"]},
    "KS": {"name": "Kansas", "fips": "20", "metros": ["Wichita", "Topeka", "Overland Park", "Kansas City"]},
    "MI": {"name": "Michigan", "fips": "26", "metros": ["Detroit", "Grand Rapids", "Lansing", "Ann Arbor", "Flint"]},
    "MN": {"name": "Minnesota", "fips": "27", "metros": ["Minneapolis", "Saint Paul", "St. Paul", "Rochester", "Duluth"]},
    "MO": {"name": "Missouri", "fips": "29", "metros": ["St. Louis", "Saint Louis", "Kansas City", "Columbia", "Springfield"]},
    "NE": {"name": "Nebraska", "fips": "31", "metros": ["Omaha", "Lincoln", "Grand Island"]},
    "OH": {"name": "Ohio", "fips": "39", "metros": ["Columbus", "Cleveland", "Cincinnati", "Toledo", "Dayton", "Akron"]},
    "WI": {"name": "Wisconsin", "fips": "55", "metros": ["Milwaukee", "Madison", "Green Bay", "Appleton", "Racine"]},
}

REGIONAL_PHRASES = [
    "midwest",
    "midwestern",
    "great lakes",
    "upper midwest",
    "corn belt",
]

WAGE_TERMS: dict[str, list[str]] = {
    "wage theft": ["wage theft", "stolen wages"],
    "overtime": ["overtime", "regular rate", "time and one-half", "time and a half"],
    "back wages": ["back wages", "back pay", "unpaid wages", "wages owed"],
    "minimum wage": ["minimum wage", "subminimum wage"],
    "tip credit": ["tip credit", "tip pool", "tips", "tipped employee"],
    "prevailing wage": ["prevailing wage", "davis-bacon", "dbra", "service contract act"],
    "misclassification": ["misclassification", "misclassified", "independent contractor"],
    "child labor": ["child labor", "minor workers", "underage workers"],
    "payroll fraud": ["payroll fraud", "off the clock", "off-the-clock", "payroll records"],
    "FMLA": ["family and medical leave", "fmla"],
    "H-2A": ["h-2a", "h2a", "agricultural visa"],
    "H-2B": ["h-2b", "h2b", "temporary nonagricultural"],
    "MSPA": ["mspa", "migrant and seasonal agricultural worker protection"],
    "SCA": ["service contract act", "sca"],
    "DBRA": ["davis-bacon", "dbra", "davis bacon"],
    "EPPA": ["employee polygraph protection", "eppa"],
    "Section 14(c)": ["14(c)", "section 14(c)", "subminimum wage certificate"],
    "FLSA": ["fair labor standards act", "flsa"],
}

STATUTE_TERMS: dict[str, list[str]] = {
    "FLSA": [
        "fair labor standards act",
        "flsa",
        "overtime",
        "minimum wage",
        "back wages",
        "tip credit",
        "tip pool",
        "child labor",
        "regular rate",
    ],
    "DBRA": ["davis-bacon", "davis bacon", "dbra", "prevailing wage"],
    "SCA": ["service contract act", "sca"],
    "FMLA": ["family and medical leave", "fmla"],
    "MSPA": ["mspa", "migrant and seasonal agricultural worker protection"],
    "H-2A": ["h-2a", "h2a", "agricultural visa"],
    "H-2B": ["h-2b", "h2b", "temporary nonagricultural"],
    "Section 14(c)": ["14(c)", "section 14(c)", "subminimum wage certificate"],
    "EPPA": ["employee polygraph protection", "eppa"],
}

VULNERABLE_SECTORS: dict[str, list[str]] = {
    "restaurants": ["restaurant", "restaurants", "fast food", "food service", "bar ", "bars ", "cafe", "diner"],
    "construction": ["construction", "contractor", "roofing", "drywall", "concrete", "electrical", "plumbing"],
    "agriculture": ["agriculture", "farm", "farms", "crop", "dairy", "greenhouse", "nursery", "orchard"],
    "warehousing": ["warehouse", "warehousing", "logistics", "distribution center", "fulfillment"],
    "home care": ["home care", "home health", "caregiver", "personal care aide"],
    "nursing": ["nursing", "nursing home", "skilled nursing", "long-term care", "assisted living"],
    "staffing": ["staffing", "temp agency", "temporary agency", "labor broker"],
    "janitorial": ["janitorial", "cleaning service", "custodial"],
    "hospitality": ["hotel", "motel", "hospitality", "housekeeping"],
    "meatpacking": ["meatpacking", "meat processing", "slaughterhouse", "poultry", "chicken plant"],
    "landscaping": ["landscaping", "landscape", "lawn care", "snow removal"],
    "garment": ["garment", "sewing", "apparel"],
    "car wash": ["car wash", "auto wash"],
    "gig and delivery": ["gig worker", "delivery driver", "rideshare", "courier"],
}

TREND_TIE_TERMS = [
    "layoff",
    "closure",
    "strike",
    "unemployment",
    "immigration",
    "heat",
    "housing",
    "recruitment",
    "staffing shortage",
    "bankruptcy",
]

OFFICIAL_HINTS = [
    "department of labor",
    "wage and hour division",
    "whd",
    "state attorney general",
    "attorney general",
    "civil money penalty",
    "consent judgment",
    "debarment",
]

EXPLICIT_WHD_SCOPE_TERMS = [
    "fair labor standards act",
    "flsa",
    "minimum wage",
    "overtime",
    "regular rate",
    "tip credit",
    "tip pool",
    "davis-bacon",
    "davis bacon",
    "dbra",
    "service contract act",
    "mspa",
    "migrant and seasonal agricultural worker protection",
    "h-2a",
    "h2a",
    "h-2b",
    "h2b",
    "family and medical leave",
    "fmla",
    "employee polygraph protection",
    "eppa",
    "14(c)",
    "section 14(c)",
    "child labor",
    "misclassification",
]

RSS_SOURCES = [
    {
        "name": "DOL National News Releases",
        "url": "https://www.dol.gov/rss/releases.xml",
        "source_type": "official",
    },
]


def load_env(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    run_handler = logging.FileHandler(Path("logs") / "run.log", encoding="utf-8")
    run_handler.setLevel(logging.INFO)
    run_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    err_handler = logging.FileHandler(Path("logs") / "err.log", encoding="utf-8")
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))

    logger.addHandler(run_handler)
    logger.addHandler(err_handler)


def db_path() -> Path:
    return Path(os.environ.get(DB_ENV, DEFAULT_DB))


def connect_db(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists items (
            id integer primary key autoincrement,
            hash text not null unique,
            title text not null,
            link text not null,
            source text not null,
            source_type text not null,
            published text,
            collected_at text not null,
            summary text,
            raw text,
            score integer not null default 0,
            states text,
            statutes text,
            sectors text,
            topics text,
            matched_terms text
        )
        """
    )
    conn.execute("create index if not exists idx_items_collected_at on items(collected_at)")
    conn.execute("create index if not exists idx_items_score on items(score)")
    conn.commit()


def item_hash(title: str, link: str) -> str:
    value = f"{title.strip()}|{link.strip()}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    replacements = {
        "\N{LEFT SINGLE QUOTATION MARK}": "'",
        "\N{RIGHT SINGLE QUOTATION MARK}": "'",
        "\N{LEFT DOUBLE QUOTATION MARK}": '"',
        "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
        "\N{NON-BREAKING HYPHEN}": "-",
        "\N{EN DASH}": "-",
        "\N{EM DASH}": "-",
        "\N{REPLACEMENT CHARACTER}": "'",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = text.replace("\N{NON-BREAKING HYPHEN}", "-")
    text = text.replace("\N{EN DASH}", "-").replace("\N{EM DASH}", "-")
    return re.sub(r"\s+", " ", text)


def contains_phrase(text: str, phrase: str) -> bool:
    phrase_norm = normalize_for_match(phrase)
    if re.fullmatch(r"[a-z0-9-]+", phrase_norm):
        return re.search(rf"(?<![a-z0-9-]){re.escape(phrase_norm)}(?![a-z0-9-])", text) is not None
    return phrase_norm in text


def find_geo(text: str) -> tuple[list[str], bool]:
    found: set[str] = set()
    normalized = normalize_for_match(text)
    for code, meta in MIDWEST_STATES.items():
        if contains_phrase(normalized, meta["name"]):
            found.add(code)
        if re.search(rf"(?<![A-Z]){code}(?![A-Z])", text):
            found.add(code)
        for metro in meta["metros"]:
            if contains_phrase(normalized, metro):
                found.add(code)
    regional_only = any(contains_phrase(normalized, phrase) for phrase in REGIONAL_PHRASES)
    return sorted(found), regional_only


def find_terms(text: str, mapping: dict[str, list[str]]) -> list[str]:
    normalized = normalize_for_match(text)
    found = []
    for label, terms in mapping.items():
        if any(contains_phrase(normalized, term) for term in terms):
            found.append(label)
    return found


def is_official_item(item: dict[str, Any], text: str) -> bool:
    source_type = str(item.get("source_type", "")).lower()
    source = normalize_for_match(str(item.get("source", "")))
    normalized = normalize_for_match(text)
    if source_type == "official":
        return True
    return any(hint in source or hint in normalized for hint in OFFICIAL_HINTS)


def classify_item(item: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(
        [
            clean_text(item.get("title")),
            clean_text(item.get("summary")),
            clean_text(item.get("source")),
        ]
    )
    states, regional_only = find_geo(text)
    topics = find_terms(text, WAGE_TERMS)
    statutes = find_terms(text, STATUTE_TERMS)
    sectors = find_terms(text, VULNERABLE_SECTORS)
    trend_terms = find_terms(text, {term: [term] for term in TREND_TIE_TERMS})
    official = is_official_item(item, text)
    wage_language = bool(topics or statutes)
    generic_market_noise = not wage_language and not official

    score = 0
    if official:
        score += 3
    if wage_language:
        score += 3
    if states:
        score += 2
    if sectors:
        score += 2
    if trend_terms:
        score += 1
    if generic_market_noise:
        score -= 2

    return {
        "score": score,
        "states": states,
        "regional_only": regional_only,
        "has_midwest_geo": bool(states),
        "topics": topics,
        "statutes": statutes,
        "sectors": sectors,
        "trend_terms": trend_terms,
        "matched_terms": sorted(set(topics + statutes + sectors + trend_terms)),
        "official": official,
        "wage_language": wage_language,
        "generic_market_noise": generic_market_noise,
    }


def has_whd_scope(item: dict[str, Any]) -> bool:
    text = normalize_for_match(
        " ".join(
            [
                clean_text(item.get("title")),
                clean_text(item.get("summary")),
                clean_text(item.get("source")),
                clean_text(item.get("link")),
            ]
        )
    )
    return any(
        marker in text
        for marker in [
            "wage and hour division",
            "dol.gov/agencies/whd",
            "/whd/",
            "whd",
        ]
    )


def is_dol_all_agency_item(item: dict[str, Any]) -> bool:
    source = normalize_for_match(clean_text(item.get("source")))
    link = normalize_for_match(clean_text(item.get("link")))
    return "dol national news releases" in source or "dol.gov/newsroom/releases/" in link


def has_explicit_whd_theory(item: dict[str, Any]) -> bool:
    text = normalize_for_match(" ".join([clean_text(item.get("title")), clean_text(item.get("summary"))]))
    return any(contains_phrase(text, term) for term in EXPLICIT_WHD_SCOPE_TERMS)


def save_item(conn: sqlite3.Connection, item: dict[str, Any]) -> bool:
    title = clean_text(item.get("title"))
    link = clean_text(item.get("link"))
    if not title or not link:
        return False
    classified = classify_item(item)
    row = {
        "hash": item_hash(title, link),
        "title": title,
        "link": link,
        "source": clean_text(item.get("source") or "Unknown"),
        "source_type": clean_text(item.get("source_type") or "news"),
        "published": clean_text(item.get("published")),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "summary": clean_text(item.get("summary")),
        "raw": item.get("raw") if isinstance(item.get("raw"), str) else json.dumps(item.get("raw", {}), ensure_ascii=True),
        "score": classified["score"],
        "states": ",".join(classified["states"]),
        "statutes": ",".join(classified["statutes"]),
        "sectors": ",".join(classified["sectors"]),
        "topics": ",".join(classified["topics"]),
        "matched_terms": ",".join(classified["matched_terms"]),
    }
    try:
        conn.execute(
            """
            insert into items (
                hash, title, link, source, source_type, published, collected_at,
                summary, raw, score, states, statutes, sectors, topics, matched_terms
            ) values (
                :hash, :title, :link, :source, :source_type, :published, :collected_at,
                :summary, :raw, :score, :states, :statutes, :sectors, :topics, :matched_terms
            )
            """,
            row,
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def should_keep(item: dict[str, Any]) -> bool:
    classified = classify_item(item)
    if not classified["has_midwest_geo"]:
        return False
    if is_dol_all_agency_item(item) and not has_whd_scope(item) and not has_explicit_whd_theory(item):
        return False
    if classified["wage_language"]:
        return True
    return bool(classified["official"] and has_whd_scope(item))


def parse_any_date(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    if not text:
        return ""
    for parser in (
        lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
        parsedate_to_datetime,
    ):
        try:
            parsed = parser(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError, OverflowError):
            continue
    gdelt_match = re.fullmatch(r"(\d{8})T(\d{6})Z?", text)
    if gdelt_match:
        parsed = datetime.strptime("".join(gdelt_match.groups()), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    return text


def require_requests() -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed. Run: python -m pip install -r requirements.txt")
    return requests


def collect_rss_source(source: dict[str, str]) -> list[dict[str, Any]]:
    if feedparser is None:
        raise RuntimeError("feedparser is not installed. Run: python -m pip install -r requirements.txt")
    parsed = feedparser.parse(source["url"])
    if getattr(parsed, "bozo", False):
        logging.warning("RSS parse warning for %s: %s", source["name"], getattr(parsed, "bozo_exception", "unknown"))
    items = []
    for entry in parsed.entries:
        summary = clean_text(entry.get("summary") or entry.get("description") or "")
        item = {
            "title": clean_text(entry.get("title")),
            "link": clean_text(entry.get("link")),
            "source": source["name"],
            "source_type": source["source_type"],
            "published": parse_any_date(entry.get("published") or entry.get("updated")),
            "summary": summary,
            "raw": json.dumps(dict(entry), ensure_ascii=True, default=str),
        }
        if should_keep(item):
            items.append(item)
    return items


def gdelt_query() -> str:
    wage = [
        '"wage theft"',
        '"back wages"',
        '"minimum wage"',
        '"tip credit"',
        '"prevailing wage"',
        '"child labor"',
        '"payroll fraud"',
        '"misclassification"',
        '"Davis-Bacon"',
        '"service contract act"',
        '"H-2A"',
        '"H-2B"',
        "overtime",
        "FMLA",
        "FLSA",
    ]
    geo = []
    for code, meta in MIDWEST_STATES.items():
        geo.append(f'"{meta["name"]}"')
        geo.append(code)
        geo.extend(f'"{metro}"' for metro in meta["metros"][:2])
    return f"({' OR '.join(wage)}) ({' OR '.join(geo)}) sourcecountry:US"


def collect_gdelt(days: int = 7, maxrecords: int = 75) -> list[dict[str, Any]]:
    http = require_requests()
    params = {
        "query": gdelt_query(),
        "mode": "artlist",
        "format": "json",
        "sort": "datedesc",
        "maxrecords": str(maxrecords),
        "timespan": f"{days}d",
    }
    response = http.get(GDELT_API, params=params, timeout=30)
    if response.status_code == 429:
        raise RuntimeError("GDELT DOC 2.0 returned 429 rate limit; retry later or reduce collection frequency")
    response.raise_for_status()
    data = response.json()
    items = []
    for article in data.get("articles", []):
        item = {
            "title": clean_text(article.get("title")),
            "link": clean_text(article.get("url")),
            "source": clean_text(article.get("sourceCountry") or article.get("domain") or "GDELT"),
            "source_type": "news",
            "published": parse_any_date(article.get("seendate")),
            "summary": clean_text(article.get("title")),
            "raw": json.dumps(article, ensure_ascii=True, default=str),
        }
        if should_keep(item):
            items.append(item)
    return items


def collect_newsapi(days: int = 7, page_size: int = 50) -> list[dict[str, Any]]:
    key = os.environ.get("NEWSAPI_KEY")
    if not key:
        logging.info("NEWSAPI_KEY missing; NewsAPI collector skipped")
        return []
    http = require_requests()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    params = {
        "q": gdelt_query().replace("sourcecountry:US", ""),
        "language": "en",
        "sortBy": "publishedAt",
        "from": since,
        "pageSize": str(page_size),
        "apiKey": key,
    }
    response = http.get(NEWSAPI_API, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "ok":
        raise RuntimeError(f"NewsAPI returned {data.get('status')}: {data.get('message')}")
    items = []
    for article in data.get("articles", []):
        source = article.get("source") or {}
        item = {
            "title": clean_text(article.get("title")),
            "link": clean_text(article.get("url")),
            "source": clean_text(source.get("name") or "NewsAPI"),
            "source_type": "news",
            "published": parse_any_date(article.get("publishedAt")),
            "summary": clean_text(article.get("description") or article.get("content")),
            "raw": json.dumps(article, ensure_ascii=True, default=str),
        }
        if should_keep(item):
            items.append(item)
    return items


def run_collect(args: argparse.Namespace) -> int:
    conn = connect_db()
    collected = 0
    inserted = 0
    collectors: list[tuple[str, Any]] = []
    if not args.no_rss:
        for source in RSS_SOURCES:
            collectors.append((source["name"], lambda source=source: collect_rss_source(source)))
    if not args.no_gdelt:
        collectors.append(("GDELT DOC 2.0", lambda: collect_gdelt(args.days, args.maxrecords)))
    if args.newsapi:
        collectors.append(("NewsAPI", lambda: collect_newsapi(args.days, min(args.maxrecords, 100))))

    for name, collector in collectors:
        try:
            items = collector()
            collected += len(items)
            for item in items:
                if save_item(conn, item):
                    inserted += 1
            logging.info("collector=%s kept=%s inserted=%s", name, len(items), inserted)
        except Exception as exc:  # noqa: BLE001 - feed isolation is required
            logging.error("collector=%s failed: %s\n%s", name, exc, traceback.format_exc())
            print(f"collector failed: {name}: {exc}", file=sys.stderr)
    print(f"collectors kept {collected}; inserted {inserted}; db={db_path()}")
    return 0


def series_id_for_state(code: str) -> str:
    return f"LASST{MIDWEST_STATES[code]['fips']}0000000000003"


def trend_label(values: list[float]) -> str:
    if len(values) < 2:
        return "flat"
    change = values[-1] - values[0]
    if change >= 0.2:
        return "rising"
    if change <= -0.2:
        return "falling"
    return "flat"


def fetch_bls_trends() -> list[dict[str, Any]]:
    http = require_requests()
    now = datetime.now(timezone.utc)
    series = [series_id_for_state(code) for code in MIDWEST_STATES]
    payload: dict[str, Any] = {
        "seriesid": series,
        "startyear": str(now.year - 2),
        "endyear": str(now.year),
    }
    key = os.environ.get("BLS_API_KEY")
    if key:
        payload["registrationkey"] = key
    response = http.post(BLS_API, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS API returned {data.get('status')}: {data.get('message')}")

    by_series = {series_id_for_state(code): code for code in MIDWEST_STATES}
    rows = []
    for series_data in data.get("Results", {}).get("series", []):
        sid = series_data.get("seriesID")
        code = by_series.get(sid)
        if not code:
            continue
        observations = []
        for point in series_data.get("data", []):
            period = str(point.get("period", ""))
            if not re.fullmatch(r"M\d{2}", period):
                continue
            try:
                month = datetime(int(point["year"]), int(period[1:]), 1, tzinfo=timezone.utc)
                value = float(point["value"])
            except (KeyError, TypeError, ValueError):
                continue
            observations.append((month, value))
        observations.sort(key=lambda row: row[0])
        last12 = observations[-12:]
        if not last12:
            continue
        values = [value for _, value in last12]
        rows.append(
            {
                "state": code,
                "state_name": MIDWEST_STATES[code]["name"],
                "series": sid,
                "latest_month": last12[-1][0].strftime("%Y-%m"),
                "latest_rate": values[-1],
                "change_12mo": round(values[-1] - values[0], 1) if len(values) > 1 else 0.0,
                "trend": trend_label(values),
                "months": len(last12),
            }
        )
    rows.sort(key=lambda row: row["state"])
    return rows


def render_trend_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No BLS trend rows available."
    lines = [
        "| State | Series | Latest month | Rate | 12-mo change | Trend |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['state']} | {row['series']} | {row['latest_month']} | "
            f"{row['latest_rate']:.1f}% | {row['change_12mo']:+.1f} | {row['trend']} |"
        )
    return "\n".join(lines)


def run_trends(args: argparse.Namespace) -> int:
    try:
        rows = fetch_bls_trends()
        output = render_trend_table(rows)
    except Exception as exc:  # noqa: BLE001 - command should fail closed
        logging.error("BLS trends failed: %s\n%s", exc, traceback.format_exc())
        output = f"BLS trend fetch failed: {exc}"
        print(output, file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


def parse_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def query_items(conn: sqlite3.Connection, days: int) -> list[dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        select *
        from items
        where collected_at >= ?
        order by score desc, published desc, collected_at desc
        """,
        (since,),
    ).fetchall()
    return [dict(row) for row in rows]


def make_snippet(text: str, limit: int = 280) -> str:
    cleaned = clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def display_date(value: Any) -> str:
    parsed = parse_any_date(value)
    if not parsed:
        return "unknown date"
    try:
        return datetime.fromisoformat(parsed.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)


def topic_for_item(item: dict[str, Any]) -> str:
    statutes = parse_list(item.get("statutes"))
    topics = parse_list(item.get("topics"))
    sectors = parse_list(item.get("sectors"))
    if statutes:
        return ", ".join(statutes)
    if topics:
        return ", ".join(topics[:3])
    if sectors:
        return ", ".join(sectors[:3])
    return "wage and hour signal"


def render_item(item: dict[str, Any]) -> str:
    where = ", ".join(parse_list(item.get("states"))) or "Midwest cue not confirmed"
    source = clean_text(item.get("source") or "Unknown")
    date = display_date(item.get("published") or item.get("collected_at"))
    snippet_source = item.get("summary") or item.get("title") or ""
    lines = [
        f"- Where: {where}",
        f"  Topic: {topic_for_item(item)}",
        f"  Source with date: {source}, {date}",
        f"  Score: {item.get('score', 0)}",
        f"  Snippet: {make_snippet(str(snippet_source), 280)}",
        f"  Link: {item.get('link')}",
    ]
    return "\n".join(lines)


def watchlist(items: list[dict[str, Any]]) -> str:
    groups: dict[str, set[str]] = defaultdict(set)
    for item in items:
        states = parse_list(item.get("states")) or ["unknown"]
        labels = parse_list(item.get("topics")) or parse_list(item.get("statutes")) or ["general wage signal"]
        for label in labels[:3]:
            groups[label].update(states)
    if not groups:
        return "No watchlist topics in the current window."
    lines = []
    for topic, states in sorted(groups.items(), key=lambda row: (-len(row[1]), row[0])):
        state_text = ", ".join(sorted(states))
        lines.append(f"- {topic}: {state_text}")
    return "\n".join(lines)


def watchlist_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for item in items:
        states = parse_list(item.get("states")) or ["unknown"]
        labels = parse_list(item.get("topics")) or parse_list(item.get("statutes")) or ["general wage signal"]
        for label in labels[:3]:
            groups[label].update(states)
    return [
        {"topic": topic, "states": sorted(states)}
        for topic, states in sorted(groups.items(), key=lambda row: (-len(row[1]), row[0]))
    ]


def analyst_synthesis(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    state_counts = Counter(state for item in items for state in parse_list(item.get("states")))
    sector_counts = Counter(sector for item in items for sector in parse_list(item.get("sectors")))
    topic_counts = Counter(topic for item in items for topic in parse_list(item.get("topics")))
    parts = []
    if state_counts:
        parts.append(f"State concentration: {', '.join(f'{k} ({v})' for k, v in state_counts.most_common(4))}.")
    if sector_counts:
        parts.append(f"Sector concentration: {', '.join(f'{k} ({v})' for k, v in sector_counts.most_common(4))}.")
    if topic_counts:
        parts.append(f"Wage theory concentration: {', '.join(f'{k} ({v})' for k, v in topic_counts.most_common(4))}.")
    return " ".join(parts)


def story_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": clean_text(item.get("title")),
        "where": parse_list(item.get("states")),
        "topic": topic_for_item(item),
        "source": clean_text(item.get("source") or "Unknown"),
        "date": display_date(item.get("published") or item.get("collected_at")),
        "score": int(item.get("score") or 0),
        "snippet": make_snippet(str(item.get("summary") or item.get("title") or ""), 280),
        "link": clean_text(item.get("link")),
        "statutes": parse_list(item.get("statutes")),
        "sectors": parse_list(item.get("sectors")),
        "terms": parse_list(item.get("matched_terms")),
    }


def render_pages_data(items: list[dict[str, Any]], trend_rows: list[dict[str, Any]] | None, days: int) -> dict[str, Any]:
    stories = [story_card(item) for item in items if int(item.get("score") or 0) >= 3]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "stories": stories,
        "trends": trend_rows or [],
        "watchlist": watchlist_rows(items),
        "summary": analyst_synthesis(items),
        "empty_state": {
            "title": "No current Midwest WHD story captured",
            "body": "Run the collector again or enable additional sources. The interface will populate from stories.json when the pipeline captures in-scope items.",
        },
    }


def render_digest(items: list[dict[str, Any]], trend_rows: list[dict[str, Any]] | None, days: int) -> str:
    top_items = [item for item in items if int(item.get("score") or 0) >= 3][:10]
    trend_rows = trend_rows or []
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Midwest Wage News Intelligence Brief",
        "",
        f"Window: last {days} days",
        f"Generated: {generated}",
        "",
        "## Top enforcement items",
    ]
    if top_items:
        lines.extend(render_item(item) for item in top_items)
    else:
        lines.append("No scored Midwest wage and hour enforcement items in the current window.")
    lines.extend(["", "## Labor trend signals", render_trend_table(trend_rows), "", "## Watchlist", watchlist(items)])
    synthesis = analyst_synthesis(items)
    if synthesis:
        lines.extend(["", "## Analyst synthesis", synthesis])
    return "\n".join(lines).rstrip() + "\n"


def run_digest(args: argparse.Namespace) -> int:
    conn = connect_db()
    items = [item for item in query_items(conn, args.days) if should_keep(item)]
    trend_rows: list[dict[str, Any]] = []
    if not args.no_trends:
        try:
            trend_rows = fetch_bls_trends()
        except Exception as exc:  # noqa: BLE001 - digest must fail closed on data
            logging.error("BLS trend table unavailable for digest: %s\n%s", exc, traceback.format_exc())
            trend_rows = []
    brief = render_digest(items, trend_rows, args.days)
    if args.out:
        Path(args.out).write_text(brief, encoding="utf-8")
    print(brief)
    return 0


def run_site_data(args: argparse.Namespace) -> int:
    conn = connect_db()
    items = [item for item in query_items(conn, args.days) if should_keep(item)]
    trend_rows: list[dict[str, Any]] = []
    if not args.no_trends:
        try:
            trend_rows = fetch_bls_trends()
        except Exception as exc:  # noqa: BLE001 - site data can render without trends
            logging.error("BLS trend table unavailable for site data: %s\n%s", exc, traceback.format_exc())
    data = render_pages_data(items, trend_rows, args.days)
    Path(args.out).write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def run_all(args: argparse.Namespace) -> int:
    collect_args = argparse.Namespace(
        days=args.days,
        maxrecords=args.maxrecords,
        no_rss=args.no_rss,
        no_gdelt=args.no_gdelt,
        newsapi=args.newsapi,
    )
    collect_code = run_collect(collect_args)
    digest_args = argparse.Namespace(days=args.days, out=args.out, no_trends=args.no_trends)
    digest_code = run_digest(digest_args)
    return collect_code or digest_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Midwest wage and hour news intelligence pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="collect RSS, GDELT, and optional NewsAPI items")
    collect.add_argument("--days", type=int, default=7)
    collect.add_argument("--maxrecords", type=int, default=75)
    collect.add_argument("--no-rss", action="store_true")
    collect.add_argument("--no-gdelt", action="store_true")
    collect.add_argument("--newsapi", action="store_true", help="enable NewsAPI collector; requires NEWSAPI_KEY")
    collect.set_defaults(func=run_collect)

    trends = sub.add_parser("trends", help="fetch BLS LASST unemployment trend table")
    trends.add_argument("--out")
    trends.set_defaults(func=run_trends)

    digest = sub.add_parser("digest", help="render markdown intelligence brief")
    digest.add_argument("--days", type=int, default=7)
    digest.add_argument("--out")
    digest.add_argument("--no-trends", action="store_true")
    digest.set_defaults(func=run_digest)

    site_data = sub.add_parser("site-data", help="write stories.json for the GitHub Pages UI")
    site_data.add_argument("--days", type=int, default=7)
    site_data.add_argument("--out", default="stories.json")
    site_data.add_argument("--no-trends", action="store_true")
    site_data.set_defaults(func=run_site_data)

    all_cmd = sub.add_parser("all", help="collect then render digest")
    all_cmd.add_argument("--days", type=int, default=7)
    all_cmd.add_argument("--maxrecords", type=int, default=75)
    all_cmd.add_argument("--no-rss", action="store_true")
    all_cmd.add_argument("--no-gdelt", action="store_true")
    all_cmd.add_argument("--newsapi", action="store_true")
    all_cmd.add_argument("--no-trends", action="store_true")
    all_cmd.add_argument("--out", default="brief.md")
    all_cmd.set_defaults(func=run_all)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_env()
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as exc:  # noqa: BLE001 - command entrypoint should log hard failures
        logging.error("command failed: %s\n%s", exc, traceback.format_exc())
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
