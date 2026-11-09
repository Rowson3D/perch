import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perch import traffic as TR  # noqa: E402

SOURCES = [
    {
        "provider": "vercel",
        "project": "prj_1",
        "team": "team_1",
        "name": "tribe",
        "domains": ["tribeperformancesd.com"],
    },
    {"provider": "vercel", "project": "prj_2", "team": None, "name": "d2", "domains": ["www.d2property.com"]},
    {"provider": "cloudflare", "zone": "z1", "name": "shopbendys.com", "domains": ["shopbendys.com"]},
]


class MatchTests(unittest.TestCase):
    def test_exact_domain(self):
        self.assertEqual(TR.match_source("https://tribeperformancesd.com/", SOURCES)["project"], "prj_1")

    def test_www_either_way(self):
        self.assertEqual(TR.match_source("https://www.tribeperformancesd.com/", SOURCES)["project"], "prj_1")
        self.assertEqual(TR.match_source("https://d2property.com/", SOURCES)["project"], "prj_2")

    def test_cloudflare_zone_covers_subdomains(self):
        self.assertEqual(TR.match_source("https://shop.shopbendys.com/", SOURCES)["zone"], "z1")

    def test_no_match(self):
        self.assertIsNone(TR.match_source("https://example.org/", SOURCES))

    def test_link_keeps_only_what_is_needed(self):
        link = TR.link(SOURCES[0], "acct")
        self.assertEqual(
            link, {"account": "acct", "provider": "vercel", "project": "prj_1", "team": "team_1", "name": "tribe"}
        )
        self.assertNotIn("domains", link)


class CloudflareTests(unittest.TestCase):
    def test_parse(self):
        data = {
            "data": {
                "viewer": {
                    "zones": [
                        {
                            "httpRequests1dGroups": [
                                {
                                    "dimensions": {"date": "2026-11-08"},
                                    "sum": {"requests": 900, "pageViews": 300},
                                    "uniq": {"uniques": 120},
                                },
                                {
                                    "dimensions": {"date": "2026-11-09"},
                                    "sum": {"requests": 400, "pageViews": 90},
                                    "uniq": {"uniques": 40},
                                },
                            ]
                        }
                    ]
                }
            }
        }
        days = TR.parse_cloudflare(data)
        self.assertEqual(days[1], {"date": "2026-11-09", "visitors": 40, "pageviews": 90})

    def test_errors_raise(self):
        with self.assertRaises(TR.TrafficError):
            TR.parse_cloudflare({"errors": [{"message": "not authorized"}]})


class TimeTests(unittest.TestCase):
    def test_local_midnight(self):
        import datetime as dt

        now = dt.datetime(2026, 11, 9, 15, 30).timestamp()
        self.assertEqual(TR.local_midnight(0, now), dt.datetime(2026, 11, 9).timestamp())
        self.assertEqual(TR.local_midnight(6, now), dt.datetime(2026, 11, 3).timestamp())


if __name__ == "__main__":
    unittest.main()
