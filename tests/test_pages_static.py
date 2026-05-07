import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PagesStaticTests(unittest.TestCase):
    def test_pages_shell_links_theme_data_and_app(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")

        self.assertIn('<body class="tc">', html)
        self.assertIn('href="theme.css"', html)
        self.assertIn('href="app.css"', html)
        self.assertIn('src="app.js"', html)
        self.assertIn('data-source="stories.json"', html)
        self.assertIn("HoruScope", html)

    def test_readme_links_github_pages_url(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("https://uhq-actual.github.io/HoruScope/", readme)


if __name__ == "__main__":
    unittest.main()
