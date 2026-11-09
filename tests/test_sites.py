import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perch import sitecheck as S  # noqa: E402
from perch.sitecheck import fmt_pct, sites_from_text  # noqa: E402

OK = {"ok": True, "status": 200, "ms": 120.0, "error": ""}
FAIL = {"ok": False, "status": 502, "ms": 80.0, "error": "HTTP 502"}


class UrlTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(S.normalize_url("Example.com"), "https://example.com/")
        self.assertEqual(S.normalize_url(" http://a.b/path?q=1 "), "http://a.b/path?q=1")
        self.assertEqual(S.normalize_url("ftp://x.com"), "")
        self.assertEqual(S.normalize_url("   "), "")

    def test_registrable_domain(self):
        self.assertEqual(S.registrable_domain("www.shop.example.com"), "example.com")
        self.assertEqual(S.registrable_domain("blog.example.co.uk"), "example.co.uk")
        self.assertEqual(S.registrable_domain("example.com."), "example.com")
        self.assertIsNone(S.registrable_domain("192.168.1.10"))
        self.assertIsNone(S.registrable_domain("localhost"))

    def test_sites_from_text(self):
        sites = sites_from_text("example.com\nhttps://example.com/\n\n  shop.example.org, junk://x ")
        self.assertEqual([s["url"] for s in sites], ["https://example.com/", "https://shop.example.org/"])
        self.assertEqual(sites[1]["name"], "shop.example.org")


class RdapTests(unittest.TestCase):
    def test_parse_iso(self):
        self.assertEqual(S.parse_iso("1970-01-02T00:00:00Z"), 86400)
        self.assertEqual(S.parse_iso("1970-01-02T00:00:00.123Z"), 86400)
        self.assertIsNone(S.parse_iso("not a date"))

    def test_parse_rdap(self):
        data = {
            "events": [{"eventAction": "registration", "eventDate": "2000-01-01T00:00:00Z"},
                       {"eventAction": "expiration", "eventDate": "1970-01-03T00:00:00Z"}],
            "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                                                           ["fn", {}, "text", "Example Registrar"]]]}],
        }  # fmt: skip
        self.assertEqual(S.parse_rdap(data), {"expires": 172800, "registrar": "Example Registrar"})
        self.assertEqual(S.parse_rdap({}), {"expires": None, "registrar": None})


class MonitorTests(unittest.TestCase):
    def test_needs_consecutive_failures(self):
        m = S.SiteMonitor()
        self.assertIsNone(m.record(OK, 2, now=0))
        self.assertEqual(m.status, S.UP)
        self.assertIsNone(m.record(FAIL, 2, now=60))  # one blip isn't an outage
        self.assertEqual(m.status, S.UP)
        self.assertIsNone(m.record(OK, 2, now=120))
        self.assertIsNone(m.record(FAIL, 2, now=180))
        self.assertEqual(m.record(FAIL, 2, now=240), "down")
        self.assertEqual(m.status, S.DOWN)
        self.assertIsNone(m.record(FAIL, 2, now=300))  # no repeat alerts while down
        self.assertEqual(m.record(OK, 2, now=360), "up")
        inc = m.last_incident()
        self.assertEqual((inc["start"], inc["end"], inc["reason"]), (240, 360, "HTTP 502"))

    def test_down_from_unknown_at_startup(self):
        m = S.SiteMonitor()
        self.assertIsNone(m.record(FAIL, 2, now=0))
        self.assertEqual(m.status, S.UNKNOWN)
        self.assertEqual(m.record(FAIL, 2, now=60), "down")

    def test_uptime_and_response(self):
        m = S.SiteMonitor()
        for i in range(9):
            m.record(OK, 2, now=i * 60)
        m.record(FAIL, 2, now=540)
        self.assertAlmostEqual(m.uptime(24, now=600), 90.0)
        self.assertAlmostEqual(m.response_avg(3600, now=600), 120.0)
        self.assertIsNone(S.SiteMonitor().uptime(24, now=0))

    def test_round_trip_keeps_open_incident(self):
        m = S.SiteMonitor()
        m.record(FAIL, 1, now=0)
        m.ssl = {"expires": 1000, "issuer": "X"}
        restored = S.SiteMonitor(m.to_json())
        self.assertEqual(restored.status, S.DOWN)
        self.assertEqual(restored.ssl, {"expires": 1000, "issuer": "X"})
        self.assertEqual(restored.uptime(24, now=10), 0.0)
        self.assertEqual(restored.record(OK, 1, now=60), "up")

    def test_days_left_and_pct(self):
        self.assertEqual(S.SiteMonitor.days_left(86400 * 3, now=0), 3)
        self.assertIsNone(S.SiteMonitor.days_left(None))
        self.assertEqual(fmt_pct(100.0), "100%")
        self.assertEqual(fmt_pct(99.9), "99.90%")
        self.assertEqual(fmt_pct(None), "—")


if __name__ == "__main__":
    unittest.main()
