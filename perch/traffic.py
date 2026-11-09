"""Visitor numbers for the Sites card, from Vercel Web Analytics and Cloudflare.

Accounts live in config["accounts"] = [{"id", "provider", "name"}]; their API tokens live in
Windows Credential Manager (see vault.py). A site's traffic source is matched by domain:
    site["traffic"] = {"account": id, "provider": "vercel", "project": project_id, "team": team_id or None}
    site["traffic"] = {"account": id, "provider": "cloudflare", "zone": zone_id}
Network calls block - run them off the UI thread.
"""

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from perch import vault
from perch.sitecheck import TLS, USER_AGENT, hostname

VERCEL_API = "https://api.vercel.com"
CLOUDFLARE_API = "https://api.cloudflare.com/client/v4"
PROVIDERS = {"vercel": "Vercel", "cloudflare": "Cloudflare"}
TOKEN_PAGES = {
    "vercel": "https://vercel.com/account/settings/tokens",
    "cloudflare": "https://dash.cloudflare.com/profile/api-tokens",
}
TOKEN_HELP = {
    "vercel": "Create a token in Vercel under Account Settings → Tokens. Give it access to the team (or "
    "personal account) your sites are in. Read access is all Perch uses.",
    "cloudflare": "Create a token in Cloudflare under My Profile → API Tokens → Create Token → Custom token, "
    "with two permissions: Zone · Zone · Read and Zone · Analytics · Read.",
}

_OPENER = urllib.request.build_opener(urllib.request.HTTPSHandler(context=TLS))


class TrafficError(RuntimeError):
    pass


def _request(url, token, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method="POST" if data else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise TrafficError("the token was rejected - check it and its permissions") from None
        try:
            detail = json.load(e)
            msg = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else None
            msg = msg or (detail.get("errors") or [{}])[0].get("message")
        except Exception:
            msg = None
        raise TrafficError(msg or f"HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise TrafficError(str(e.reason)) from None


def _qs(params):
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)


def local_midnight(days_ago=0, now=None):
    d = dt.datetime.fromtimestamp(now or time.time()).date() - dt.timedelta(days=days_ago)
    return dt.datetime.combine(d, dt.time()).timestamp()


# ------------------------------------------------------------------ Vercel
class Vercel:
    def __init__(self, token):
        self.token = token

    def get(self, path, **params):
        return _request(f"{VERCEL_API}{path}?{_qs(params)}", self.token)

    def teams(self):
        return [{"id": t["id"], "name": t.get("name") or t.get("slug")} for t in self.get("/v2/teams").get("teams", [])]

    def projects(self, team=None):
        out, until = [], None
        for _ in range(10):  # up to 1000 projects
            data = self.get("/v9/projects", teamId=team, limit=100, until=until)
            out += [{"id": p["id"], "name": p["name"]} for p in data.get("projects", [])]
            until = (data.get("pagination") or {}).get("next")
            if not until:
                break
        return out

    def domains(self, project, team=None):
        return [d["name"].lower() for d in self.get(f"/v9/projects/{project}/domains", teamId=team).get("domains", [])]

    def sources(self):
        """Every project in the personal account and each team, with its domains."""
        out, seen = [], set()
        for team in [None, *[t["id"] for t in self.teams()]]:
            for p in self.projects(team):
                if p["id"] in seen:  # the personal account can also show up as a team
                    continue
                seen.add(p["id"])
                out.append(
                    {
                        "provider": "vercel",
                        "project": p["id"],
                        "team": team,
                        "name": p["name"],
                        "domains": self.domains(p["id"], team),
                    }
                )
        return out

    def count(self, project, team, since, until):
        data = (
            self.get(
                "/v1/query/web-analytics/visits/count",
                projectId=project,
                teamId=team,
                since=int(since * 1000),
                until=int(until * 1000),
            ).get("data")
            or {}
        )
        return {"visitors": int(data.get("visitors") or 0), "pageviews": int(data.get("pageviews") or 0)}

    def daily(self, project, team, days=7, now=None):
        now = now or time.time()
        data = (
            self.get(
                "/v1/query/web-analytics/visits/aggregate",
                projectId=project,
                teamId=team,
                by="day",
                since=int(local_midnight(days - 1, now) * 1000),
                until=int(now * 1000),
            ).get("data")
            or []
        )
        return [
            {
                "date": r.get("timestamp", "")[:10],
                "visitors": int(r.get("visitors") or 0),
                "pageviews": int(r.get("pageviews") or 0),
            }
            for r in data
        ]

    def stats(self, source, now=None):
        now = now or time.time()
        p, t = source["project"], source.get("team")
        return {
            "today": self.count(p, t, local_midnight(0, now), now),
            "week": self.count(p, t, local_midnight(6, now), now),
            "days": self.daily(p, t, 7, now),
        }


# ------------------------------------------------------------------ Cloudflare
CF_QUERY = """
query ($zone: String!, $since: Date!, $until: Date!) {
  viewer { zones(filter: {zoneTag: $zone}) {
    httpRequests1dGroups(limit: 10, filter: {date_geq: $since, date_leq: $until}, orderBy: [date_ASC]) {
      dimensions { date } sum { requests pageViews } uniq { uniques }
    } } }
}"""


def parse_cloudflare(data):
    if data.get("errors"):
        raise TrafficError(data["errors"][0].get("message", "Cloudflare returned an error"))
    zones = ((data.get("data") or {}).get("viewer") or {}).get("zones") or []
    groups = zones[0].get("httpRequests1dGroups", []) if zones else []
    return [
        {
            "date": g["dimensions"]["date"],
            "visitors": int(g["uniq"]["uniques"]),
            "pageviews": int(g["sum"]["pageViews"]),
        }
        for g in groups
    ]


class Cloudflare:
    def __init__(self, token):
        self.token = token

    def sources(self):
        out, page = [], 1
        while True:
            data = _request(f"{CLOUDFLARE_API}/zones?{_qs({'per_page': 50, 'page': page})}", self.token)
            if not data.get("success", True):
                raise TrafficError((data.get("errors") or [{}])[0].get("message", "Cloudflare returned an error"))
            for z in data.get("result", []):
                out.append(
                    {"provider": "cloudflare", "zone": z["id"], "name": z["name"], "domains": [z["name"].lower()]}
                )
            info = data.get("result_info") or {}
            if page >= (info.get("total_pages") or 1):
                return out
            page += 1

    def stats(self, source, now=None):
        today = dt.datetime.now(dt.timezone.utc).date()
        body = {
            "query": CF_QUERY,
            "variables": {"zone": source["zone"], "since": str(today - dt.timedelta(days=6)), "until": str(today)},
        }
        days = parse_cloudflare(_request(f"{CLOUDFLARE_API}/graphql", self.token, body))
        last = days[-1] if days and days[-1]["date"] == str(today) else {"visitors": 0, "pageviews": 0}
        return {
            "today": {"visitors": last["visitors"], "pageviews": last["pageviews"]},
            # Cloudflare counts unique visitors per day, so the week is a sum of daily uniques
            "week": {"visitors": sum(d["visitors"] for d in days), "pageviews": sum(d["pageviews"] for d in days)},
            "days": days,
        }


# ------------------------------------------------------------------ accounts and matching
def client(account):
    token = vault.get_secret(f"account/{account['id']}")
    if not token:
        raise TrafficError("the token for this account is missing - reconnect it")
    return (Vercel if account["provider"] == "vercel" else Cloudflare)(token)


def new_account(provider, name):
    return {"id": uuid.uuid4().hex[:10], "provider": provider, "name": name}


def connect(provider, token):
    """Check a token and list what it can see. Returns the sources (projects / zones)."""
    sources = (Vercel if provider == "vercel" else Cloudflare)(token).sources()
    if not sources:
        raise TrafficError(
            "connected, but the token can't see any " + ("projects" if provider == "vercel" else "sites")
        )
    return sources


def match_source(url, sources):
    """The project/zone serving this site, by domain (exact, then www, then the zone that contains it)."""
    host = hostname(url).lower()
    bare = host[4:] if host.startswith("www.") else host
    for s in sources:
        if host in s["domains"] or bare in s["domains"] or f"www.{bare}" in s["domains"]:
            return s
    for s in sources:
        if s["provider"] == "cloudflare" and any(host.endswith("." + d) for d in s["domains"]):
            return s
    return None


def link(source, account_id):
    """What gets stored on a site."""
    keep = {k: source[k] for k in ("provider", "project", "team", "zone", "name") if k in source}
    return {"account": account_id, **keep}


def fetch(account, link_info, now=None):
    return client(account).stats(link_info, now)
