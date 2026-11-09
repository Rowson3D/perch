"""Website checks for the Sites card: HTTP up/down, SSL certificate expiry, domain expiry (RDAP),
plus SiteMonitor, the per-site state machine (down after N failures, incidents, uptime buckets).

Network functions block - run them off the UI thread.
"""

import datetime as dt
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import deque

from perch import REPO_URL, __version__

UP, DOWN, UNKNOWN, PAUSED = "up", "down", "unknown", "paused"
USER_AGENT = f"Perch/{__version__} (+{REPO_URL})"
SAMPLE_SECONDS = 24 * 3600  # response-time samples kept for graphs
BUCKET_DAYS = 30  # hourly up/down counts kept for uptime %
MAX_INCIDENTS = 50
# Second-level registries where the registrable domain has three labels (example.co.uk).
MULTI_PART_TLDS = {
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "com.au", "net.au", "org.au",
    "co.nz", "org.nz", "net.nz", "co.za", "com.br", "com.mx", "co.jp", "com.cn", "com.tw", "co.in", "co.kr",
    "com.sg", "com.tr", "com.ar", "com.co", "co.il",
}  # fmt: skip


def _tls_context():
    """Windows' certificate store plus Mozilla's (certifi). Windows only downloads root certificates
    when a browser first needs them, so on its own it can wrongly reject perfectly valid sites."""
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


TLS = _tls_context()
_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=TLS))


# ------------------------------------------------------------------ helpers
def normalize_url(text):
    """'example.com' -> 'https://example.com/'. Returns '' if it can't be a URL."""
    t = (text or "").strip()
    if not t:
        return ""
    if "://" not in t:
        t = "https://" + t
    p = urllib.parse.urlsplit(t)
    if p.scheme not in ("http", "https") or not p.hostname:
        return ""
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def hostname(url):
    return urllib.parse.urlsplit(url).hostname or ""


def registrable_domain(host):
    """'www.shop.example.co.uk' -> 'example.co.uk'. None for IPs / single labels."""
    host = (host or "").strip(".").lower()
    if not host or ":" in host or re.fullmatch(r"[\d.]+", host):
        return None
    parts = host.split(".")
    if len(parts) < 2:
        return None
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_PART_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def parse_iso(text):
    """RDAP dates like 2027-06-01T04:00:00Z or with fractions -> epoch seconds."""
    if not text:
        return None
    t = re.sub(r"\.\d+", "", text.strip()).replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def short_error(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    reason = e.reason if isinstance(e, urllib.error.URLError) else e
    if isinstance(reason, socket.gaierror):
        return "DNS lookup failed"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return f"certificate error: {reason.verify_message}"
    if isinstance(reason, ssl.SSLError):
        return "TLS handshake failed"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused"
    if isinstance(reason, ConnectionResetError):
        return "connection reset"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timed out"
    return str(reason) or type(reason).__name__


def new_site(url, name="", **extra):
    url = normalize_url(url)
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name or hostname(url),
        "url": url,
        "keyword": "",
        "admin_url": "",
        "repo_url": "",
        "check_ssl": True,
        "check_domain": True,
        "paused": False,
        **extra,
    }


def sites_from_text(text):
    """One address per line (or separated by spaces/commas) -> site dicts. Skips junk and duplicates."""
    seen, out = set(), []
    for token in (text or "").replace(",", " ").split():
        url = normalize_url(token)
        if url and url not in seen:
            seen.add(url)
            out.append(new_site(url))
    return out


def fmt_pct(p):
    if p is None:
        return "—"
    return "100%" if p >= 99.995 else f"{p:.2f}%"


# ------------------------------------------------------------------ checks
def check_http(url, keyword="", timeout=10):
    """GET the page. ok = 2xx/3xx (after redirects) and, if given, the keyword appears in the body."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    t0 = time.perf_counter()
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = resp.read(1024 * 1024 if keyword else 1)
            ms = (time.perf_counter() - t0) * 1000
            status = resp.status
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "ms": (time.perf_counter() - t0) * 1000, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001 - every failure is a "down" result
        return {"ok": False, "status": None, "ms": None, "error": short_error(e)}
    if keyword and keyword.lower() not in body.decode("utf-8", "replace").lower():
        return {"ok": False, "status": status, "ms": ms, "error": f"page is missing “{keyword}”"}
    return {"ok": True, "status": status, "ms": ms, "error": ""}


def check_ssl(host, port=443, timeout=8):
    """Certificate expiry + issuer. Raises on handshake/verification failure."""
    with (
        socket.create_connection((host, port), timeout=timeout) as sock,
        TLS.wrap_socket(sock, server_hostname=host) as tls,
    ):
        cert = tls.getpeercert()
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    return {
        "expires": ssl.cert_time_to_seconds(cert["notAfter"]),
        "issuer": issuer.get("organizationName") or issuer.get("commonName") or "",
    }


def parse_rdap(data):
    expires = registrar = None
    for ev in data.get("events") or []:
        if ev.get("eventAction") == "expiration":
            expires = parse_iso(ev.get("eventDate"))
    for ent in data.get("entities") or []:
        if "registrar" in (ent.get("roles") or []):
            card = ent.get("vcardArray") or [None, []]
            for item in card[1] if len(card) > 1 else []:
                if item and item[0] == "fn":
                    registrar = item[3]
    return {"expires": expires, "registrar": registrar}


def check_domain(domain, timeout=12):
    """Domain registration expiry via RDAP (rdap.org forwards to the right registry)."""
    req = urllib.request.Request(
        f"https://rdap.org/domain/{domain}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/rdap+json, application/json"},
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(f"no registration data published for .{domain.split('.', 1)[-1]}") from None
        raise RuntimeError(short_error(e)) from None
    except urllib.error.URLError as e:
        raise RuntimeError(short_error(e)) from None
    info = parse_rdap(data)
    if info["expires"] is None:
        raise RuntimeError("registry doesn't publish an expiry date")
    return info


# ------------------------------------------------------------------ per-site state
class SiteMonitor:
    """Tracks one site: current status with confirmation, response samples, uptime buckets, incidents."""

    def __init__(self, saved=None):
        saved = saved or {}
        self.status = UNKNOWN
        self.fails = 0
        self.last = None  # last check result + "t"
        self.since = saved.get("since")
        self.samples = deque((t, ms) for t, ms in saved.get("samples", []))  # (t, ms or None=failed)
        self.hours = {int(k): v for k, v in saved.get("hours", {}).items()}  # hour start -> [ok, total]
        self.incidents = saved.get("incidents", [])  # {"start", "end", "reason"}
        self.ssl = saved.get("ssl")  # {"expires", "issuer"}
        self.ssl_error = saved.get("ssl_error")
        self.ssl_checked = saved.get("ssl_checked", 0)
        self.domain = saved.get("domain")  # {"expires", "registrar"}
        self.domain_error = saved.get("domain_error")
        self.domain_checked = saved.get("domain_checked", 0)
        self.notified = saved.get("notified", {})  # warning key -> day it was last sent
        if self.incidents and self.incidents[-1].get("end") is None:
            self.status = DOWN  # we quit while it was down; keep the open incident

    def to_json(self):
        return {
            "since": self.since,
            "samples": list(self.samples),
            "hours": {str(k): v for k, v in self.hours.items()},
            "incidents": self.incidents[-MAX_INCIDENTS:],
            "ssl": self.ssl,
            "ssl_error": self.ssl_error,
            "ssl_checked": self.ssl_checked,
            "domain": self.domain,
            "domain_error": self.domain_error,
            "domain_checked": self.domain_checked,
            "notified": self.notified,
        }

    def record(self, result, fail_after=2, now=None):
        """Feed one HTTP check. Returns 'down', 'up' (recovered) or None."""
        now = time.time() if now is None else now
        ok = bool(result["ok"])
        self.last = {**result, "t": now}
        self.samples.append((now, result["ms"] if ok else None))
        while self.samples and self.samples[0][0] < now - SAMPLE_SECONDS:
            self.samples.popleft()
        hour = int(now // 3600 * 3600)
        bucket = self.hours.setdefault(hour, [0, 0])
        bucket[0] += ok
        bucket[1] += 1
        for h in [h for h in self.hours if h < now - BUCKET_DAYS * 86400]:
            del self.hours[h]

        if ok:
            self.fails = 0
            if self.status == DOWN:
                if self.incidents and self.incidents[-1].get("end") is None:
                    self.incidents[-1]["end"] = now
                self.status, self.since = UP, now
                return "up"
            if self.status != UP:
                self.status, self.since = UP, now
            return None

        self.fails += 1
        if self.status != DOWN and self.fails >= max(1, fail_after):
            self.status, self.since = DOWN, now
            self.incidents.append({"start": now, "end": None, "reason": result.get("error") or "down"})
            del self.incidents[:-MAX_INCIDENTS]
            return "down"
        return None

    def uptime(self, hours, now=None):
        now = time.time() if now is None else now
        ok = total = 0
        for h, (o, t) in self.hours.items():
            if h >= now - hours * 3600:
                ok += o
                total += t
        return 100.0 * ok / total if total else None

    def response_avg(self, seconds, now=None):
        now = time.time() if now is None else now
        vals = [ms for t, ms in self.samples if t >= now - seconds and ms is not None]
        return sum(vals) / len(vals) if vals else None

    def last_incident(self):
        return self.incidents[-1] if self.incidents else None

    @staticmethod
    def days_left(expires, now=None):
        if not expires:
            return None
        now = time.time() if now is None else now
        return (expires - now) / 86400
