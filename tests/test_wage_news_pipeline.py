import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import wage_news_pipeline as p


class WageNewsPipelineTests(unittest.TestCase):
    def test_geography_requires_state_or_metro_not_region_only(self):
        region_only = p.classify_item(
            {
                "title": "Midwest employers face payroll pressure",
                "summary": "A regional business survey found hiring was slow.",
                "source_type": "news",
            }
        )
        concrete = p.classify_item(
            {
                "title": "Chicago restaurant workers recover back wages",
                "summary": "The case involved overtime and minimum wage violations.",
                "source_type": "official",
            }
        )

        self.assertFalse(region_only["has_midwest_geo"])
        self.assertEqual(concrete["states"], ["IL"])
        self.assertTrue(concrete["has_midwest_geo"])

    def test_classifier_scores_official_wage_vulnerable_items(self):
        classified = p.classify_item(
            {
                "title": "US Department of Labor recovers back wages for Ohio restaurant workers",
                "summary": "Investigation found overtime and tip credit violations under the FLSA.",
                "source_type": "official",
            }
        )

        self.assertGreaterEqual(classified["score"], 10)
        self.assertIn("FLSA", classified["statutes"])
        self.assertIn("restaurants", classified["sectors"])
        self.assertIn("OH", classified["states"])

    def test_official_non_wage_items_are_not_kept(self):
        item = {
            "title": "Department of Labor cites Missouri railroad after safety complaint",
            "summary": "An OSHA whistleblower investigation involved the Federal Railroad Safety Act.",
            "source": "DOL National News Releases",
            "source_type": "official",
        }

        self.assertFalse(p.should_keep(item))

    def test_dol_all_agency_back_wage_remedy_without_whd_scope_is_not_kept(self):
        item = {
            "title": "Kansas City railroad ordered to pay back wages after safety complaint",
            "summary": "The OSHA case involved the Federal Railroad Safety Act, reinstatement, and lost wages.",
            "source": "DOL National News Releases",
            "source_type": "official",
            "link": "https://www.dol.gov/newsroom/releases/osha/example",
        }

        self.assertFalse(p.should_keep(item))

    def test_sqlite_dedupes_by_title_link_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wage_news.db"
            conn = sqlite3.connect(db_path)
            try:
                p.init_db(conn)
                item = {
                    "title": "Indiana contractor pays back wages",
                    "link": "https://example.test/story",
                    "source": "Example",
                    "source_type": "official",
                    "published": "2026-05-06T10:00:00+00:00",
                    "summary": "Back wages and overtime.",
                    "raw": "{}",
                }

                self.assertTrue(p.save_item(conn, item))
                self.assertFalse(p.save_item(conn, dict(item)))
                rows = conn.execute("select count(*) from items").fetchone()[0]
                self.assertEqual(rows, 1)
            finally:
                conn.close()

    def test_snippets_are_capped_for_digest(self):
        long_text = "x" * 400
        snippet = p.make_snippet(long_text, 280)
        self.assertLessEqual(len(snippet), 280)
        self.assertTrue(snippet.endswith("..."))

    def test_trend_label_uses_last_twelve_months(self):
        falling = [5.2, 5.1, 5.0, 4.9, 4.8, 4.7, 4.6, 4.5, 4.4, 4.3, 4.2, 4.1]
        rising = list(reversed(falling))
        flat = [4.0, 4.1, 4.0, 4.1, 4.0, 4.1, 4.0, 4.1, 4.0, 4.1, 4.0, 4.1]

        self.assertEqual(p.trend_label(falling), "falling")
        self.assertEqual(p.trend_label(rising), "rising")
        self.assertEqual(p.trend_label(flat), "flat")

    def test_digest_contains_required_sections_and_fields(self):
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "title": "Michigan warehouse contractor pays back wages",
            "link": "https://example.test/mi",
            "source": "DOL WHD",
            "source_type": "official",
            "published": now,
            "summary": "Warehouse workers were denied overtime pay.",
            "score": 10,
            "states": "MI",
            "statutes": "FLSA",
            "sectors": "warehousing",
            "topics": "back wages,overtime",
            "matched_terms": "back wages,overtime",
        }

        brief = p.render_digest([item], [], days=7)

        self.assertIn("## Top enforcement items", brief)
        self.assertIn("Where: MI", brief)
        self.assertIn("Topic: FLSA", brief)
        self.assertIn("Score: 10", brief)
        self.assertIn("## Labor trend signals", brief)
        self.assertIn("## Watchlist", brief)

    def test_pages_data_exports_story_cards_and_watchlist(self):
        item = {
            "title": "Ohio restaurant operator pays overtime back wages",
            "link": "https://example.test/oh",
            "source": "DOL WHD",
            "source_type": "official",
            "published": "2026-05-06T10:00:00+00:00",
            "summary": "Workers were denied overtime and tip-credit protections.",
            "score": 11,
            "states": "OH",
            "statutes": "FLSA",
            "sectors": "restaurants",
            "topics": "back wages,overtime,tip credit",
            "matched_terms": "back wages,overtime,tip credit",
        }
        trends = [
            {
                "state": "OH",
                "series": "LASST390000000000003",
                "latest_month": "2026-03",
                "latest_rate": 4.1,
                "change_12mo": -0.7,
                "trend": "falling",
            }
        ]

        data = p.render_pages_data([item], trends, days=7)

        self.assertEqual(data["window_days"], 7)
        self.assertEqual(data["stories"][0]["where"], ["OH"])
        self.assertEqual(data["stories"][0]["topic"], "FLSA")
        self.assertEqual(data["stories"][0]["score"], 11)
        self.assertEqual(data["trends"][0]["state"], "OH")
        self.assertEqual(data["watchlist"][0]["topic"], "back wages")
        self.assertIn("No current", p.render_pages_data([], [], days=7)["empty_state"]["title"])

    def test_curated_cases_enrich_into_story_cards(self):
        items = p.curated_midwest_story_items()

        data = p.render_pages_data(items, [], days=7)

        self.assertGreaterEqual(len(data["stories"]), 5)
        self.assertTrue(all(story["where"] for story in data["stories"]))
        self.assertTrue(any(story["source"] == "DOL WHD" for story in data["stories"]))
        self.assertTrue(any("FLSA" in story["topic"] or "child labor" in story["topic"] for story in data["stories"]))

    def test_site_data_uses_curated_fallback_when_database_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db = p.os.environ.get(p.DB_ENV)
            p.os.environ[p.DB_ENV] = str(Path(tmp) / "wage_news.db")
            out = Path(tmp) / "stories.json"
            try:
                args = p.argparse.Namespace(days=7, out=str(out), no_trends=True, no_curated=False)
                code = p.run_site_data(args)
                data = p.json.loads(out.read_text(encoding="utf-8"))
            finally:
                if original_db is None:
                    p.os.environ.pop(p.DB_ENV, None)
                else:
                    p.os.environ[p.DB_ENV] = original_db

        self.assertEqual(code, 0)
        self.assertEqual(data["source_mode"], "curated_official_cases")
        self.assertGreater(len(data["stories"]), 0)


if __name__ == "__main__":
    unittest.main()
