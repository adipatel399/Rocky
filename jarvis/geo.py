"""Intel router — turns a spoken query into camera moves + data windows.

One query can produce several "stage directions" for the HUD:
  a cinematic globe move (focus/spin) + one or more windows (weather, news with
  an inline video, a Wikipedia knowledge card, a place dossier).

Everything here is keyless and free:
  Open-Meteo (geocoding + weather) · Google News RSS · YouTube (scraped video
  id) · Wikipedia REST summary.

Synchronous urllib; the server runs resolve() in a thread pool. Any failure
returns None so the caller can fall back to the full Claude brain.
"""
import concurrent.futures
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

WMO = {
    0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Rime fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌦️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌧️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "❄️"), 73: ("Snow", "❄️"), 75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "❄️"), 80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌦️"),
    82: ("Violent showers", "⛈️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "🌨️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm, hail", "⛈️"),
    99: ("Thunderstorm, hail", "⛈️"),
}

FILLER = re.compile(
    r"\b(right now|now|today|tonight|currently|at the moment|these days|please|"
    r"jarvis|for me|the weather|weather|like|of|latest)\b", re.I)

STOPWORDS = set("the a an and or of in on at to for from with as is are was were "
                "breaking news update latest says say after before over under new "
                "how why what when who report reports amid into out".split())


def _get(url: str, timeout: float = 4.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _clean_place(raw: str) -> str:
    raw = raw.strip().strip("?.!,")
    raw = re.sub(r"^(the|in|at|for|of|about|from|to)\s+", "", raw, flags=re.I)
    raw = FILLER.sub("", raw).strip(" ,?.!")
    return re.sub(r"\s+", " ", raw)


# ------------------------------------------------------------------ geocode

_GEO_CACHE = {}
_WID = 0


def _wid():
    global _WID
    _WID += 1
    return f"g{_WID}"


def geocode(place: str):
    """Cached geocode — instant on repeat queries."""
    key = (place or "").strip().lower()
    if not key:
        return None
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    g = _geocode_nominatim(place) or _geocode_openmeteo(place)
    if g:
        _GEO_CACHE[key] = g
    return g


def _geocode_nominatim(place: str):
    """Nominatim (OpenStreetMap) — ranks by real-world prominence, so "Gujarat"
    resolves to the Indian state, not a same-named village."""
    try:
        u = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": place, "format": "json", "limit": 1,
             "addressdetails": 1, "accept-language": "en"})
        req = urllib.request.Request(u, headers={"User-Agent": "JarvisAssistant/1.0 (personal use)"})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read())
        if d:
            r0 = d[0]
            a = r0.get("address", {}) or {}
            name = (r0.get("name") or a.get("city") or a.get("town")
                    or a.get("state") or r0.get("display_name", "").split(",")[0])
            return {"name": name, "country": a.get("country"),
                    "admin1": a.get("state"), "lat": float(r0["lat"]),
                    "lng": float(r0["lon"]), "timezone": None, "population": None}
    except Exception:
        pass
    return None


def _geocode_openmeteo(place: str):
    q = urllib.parse.quote(place)
    url = (f"https://geocoding-api.open-meteo.com/v1/search?name={q}"
           "&count=10&language=en&format=json")
    try:
        results = (json.loads(_get(url)).get("results") or [])
    except Exception:
        return None
    if not results:
        return None
    ql = place.strip().lower()
    exact = [r for r in results if (r.get("name") or "").lower() == ql]
    r = max(exact or results, key=lambda x: x.get("population") or 0)
    return {"name": r.get("name"), "country": r.get("country"),
            "admin1": r.get("admin1"), "lat": r.get("latitude"),
            "lng": r.get("longitude"), "timezone": r.get("timezone"),
            "population": r.get("population")}


def timezone_at(lat, lng):
    try:
        d = json.loads(_get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}"
                            f"&longitude={lng}&current=temperature_2m&timezone=auto"))
        return d.get("timezone")
    except Exception:
        return None


def _label(g: dict) -> str:
    bits = [g.get("name")]
    if g.get("admin1") and g["admin1"] != g.get("name"):
        bits.append(g["admin1"])
    if g.get("country"):
        bits.append(g["country"])
    return ", ".join(b for b in bits if b)


def _local_time(tz: str):
    if not tz or not ZoneInfo:
        return None
    try:
        return datetime.now(ZoneInfo(tz)).strftime("%a %H:%M")
    except Exception:
        return None


# ------------------------------------------------------------------ weather

def weather(lat, lng):
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}"
           "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
           "weather_code,wind_speed_10m,is_day,precipitation,pressure_msl,cloud_cover"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max,sunrise,sunset,uv_index_max"
           "&timezone=auto&forecast_days=7")
    try:
        data = json.loads(_get(url))
    except Exception:
        return None
    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    code = int(cur.get("weather_code", -1))
    desc, emoji = WMO.get(code, ("Unknown", "🌡️"))

    days = []
    times = daily.get("time") or []
    for i, d in enumerate(times):
        dcode = int((daily.get("weather_code") or [0])[i])
        _, demoji = WMO.get(dcode, ("", "🌡️"))
        try:
            label = "Today" if i == 0 else datetime.strptime(d, "%Y-%m-%d").strftime("%a")
        except Exception:
            label = d
        days.append({"day": label, "emoji": demoji,
                     "hi": round((daily.get("temperature_2m_max") or [0])[i]),
                     "lo": round((daily.get("temperature_2m_min") or [0])[i]),
                     "pop": (daily.get("precipitation_probability_max") or [None])[i]})

    def _hm(v):
        return v.split("T")[1] if v and "T" in v else None

    return {"temp": round(cur.get("temperature_2m", 0)),
            "feels": round(cur.get("apparent_temperature", 0)),
            "desc": desc, "emoji": emoji,
            "humidity": cur.get("relative_humidity_2m"),
            "wind": round(cur.get("wind_speed_10m", 0)),
            "precip": cur.get("precipitation"),
            "pressure": round(cur.get("pressure_msl", 0)) if cur.get("pressure_msl") else None,
            "cloud": cur.get("cloud_cover"),
            "uv": round((daily.get("uv_index_max") or [None])[0]) if (daily.get("uv_index_max") or [None])[0] is not None else None,
            "sunrise": _hm((daily.get("sunrise") or [None])[0]),
            "sunset": _hm((daily.get("sunset") or [None])[0]),
            "is_day": cur.get("is_day", 1),
            "hi": (days[0]["hi"] if days else None),
            "lo": (days[0]["lo"] if days else None),
            "pop": (days[0]["pop"] if days else None),
            "days": days,
            "timezone": data.get("timezone")}


# ------------------------------------------------------------------ news

def news(query: str, limit: int = 6):
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        root = ET.fromstring(_get(url, timeout=5.0))
    except Exception:
        return None
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = ""
        src_el = it.find("source")
        if src_el is not None and src_el.text:
            source = src_el.text.strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)]
        elif " - " in title:
            head, _, tail = title.rpartition(" - ")
            if len(tail) < 40:
                title, source = head, source or tail
        items.append({"title": title, "source": source,
                      "link": (it.findtext("link") or "").strip(),
                      "published": _rel_time((it.findtext("pubDate") or "").strip())})
        if len(items) >= limit:
            break
    return items or None


def _rel_time(pubdate: str) -> str:
    if not pubdate:
        return ""
    try:
        dt = datetime.strptime(pubdate, "%a, %d %b %Y %H:%M:%S %Z")
    except Exception:
        return ""
    secs = int((datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds())
    if secs < 3600:
        return f"{max(1, secs // 60)}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def youtube_search(query: str):
    """Scrape the first video id for a query (keyless)."""
    try:
        html = _get("https://www.youtube.com/results?search_query=" +
                    urllib.parse.quote(query), timeout=5.0).decode("utf-8", "replace")
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def locate_headline(title: str):
    """Best-effort: pull a place name out of a headline and geocode it."""
    # candidate runs of Capitalised words not at sentence start noise
    cands = re.findall(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b", title or "")
    seen = []
    for c in cands:
        words = [w for w in c.split() if w.lower() not in STOPWORDS]
        if not words:
            continue
        cand = " ".join(words)
        if cand.lower() in STOPWORDS or len(cand) < 3 or cand in seen:
            continue
        seen.append(cand)
    for cand in seen[:3]:
        g = geocode(cand)
        if g and g["lat"] is not None and g.get("country"):
            return g
    return None


# ------------------------------------------------------------------ wikipedia

def wikipedia(query: str):
    q = urllib.parse.quote(query.replace(" ", "_"))
    try:
        d = json.loads(_get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{q}",
                            timeout=5.0))
    except Exception:
        return None
    if d.get("type") == "disambiguation" or not d.get("extract"):
        return None
    return {"title": d.get("title"),
            "extract": d.get("extract"),
            "thumb": (d.get("thumbnail") or {}).get("source"),
            "url": (d.get("content_urls", {}).get("desktop", {}) or {}).get("page"),
            "coords": d.get("coordinates")}


# ------------------------------------------------------------------ intents

_UI = [
    (re.compile(r"\b(full\s?screen|maximi[sz]e|blow (it|that) up|make (it|that|this) (big|bigger|full)|expand (it|that|this|the window))\b", re.I), "fullscreen"),
    (re.compile(r"\b(minimi[sz]e|shrink (it|that)|make (it|that|this) small(er)?|tuck (it|that) away)\b", re.I), "minimize"),
    (re.compile(r"\b(restore|bring (it|that) back|normal size|un-?maximi[sz]e)\b", re.I), "restore"),
    (re.compile(r"\b(close|dismiss|get rid of|clear)\s+(it|that|the window|this|everything|all)\b", re.I), "close"),
]
_WEATHER = [
    re.compile(r"\bweather\b.*?\b(?:in|at|for|of)\b\s+(?P<place>.+)$", re.I),
    re.compile(r"how('?s| is| are)\b.*?\b(?:weather|temperature|hot|cold|warm)\b.*?\bin\s+(?P<place>.+)$", re.I),
    re.compile(r"\btemperature\b.*?\bin\s+(?P<place>.+)$", re.I),
    re.compile(r"\bweather\b\s+(?P<place>[a-z .'-]+)$", re.I),
]
_NEWS = [
    re.compile(r"\b(?:news|headlines)\b.*?\b(?:in|from|about|on|regarding|for)\b\s+(?P<place>.+)$", re.I),
    re.compile(r"what('?s| is)\s+happening\b.*?\bin\s+(?P<place>.+)$", re.I),
    re.compile(r"\blatest\b.*?\b(?:news|updates?|on)\b\s+(?P<place>.+)$", re.I),
]
_NEWS_GLOBAL = re.compile(r"\b(news|headlines|what'?s happening|going on)\b", re.I)
_GLOBAL_HINT = re.compile(r"\b(worldwide|world|global|globally|international|around the world|everywhere)\b", re.I)
_LOCATE = [
    re.compile(r"\b(?:show me|take me to|locate|fly to|go to|where is|pull up|point to|zoom (?:in )?(?:to|on))\b\s+(?P<place>.+?)(?:\s+on the (?:globe|map|earth|world))?$", re.I),
    re.compile(r"(?P<place>.+?)\s+on the (?:globe|map|earth|world)$", re.I),
]
_KNOW = [
    re.compile(r"\b(?:who|what)(?:'s| is| are| was| were)\s+(?P<q>.+)$", re.I),
    re.compile(r"\b(?:tell me about|what do you know about|info on|information on|look up|define)\s+(?P<q>.+)$", re.I),
]


def _valid(p: str, maxw=6) -> bool:
    if not p or len(p) < 2 or len(p) > 60:
        return False
    return len(p.split()) <= maxw and bool(re.search(r"[a-zA-Z]", p)) and not re.search(r"[/\\{}<>]", p)


def parse_intent(text: str):
    t = text.strip()
    for rx, action in _UI:
        if rx.search(t):
            return {"kind": "ui", "action": action}
    for rx in _WEATHER:
        m = rx.search(t)
        if m and _valid(_clean_place(m.group("place"))):
            return {"kind": "weather", "place": _clean_place(m.group("place"))}
    for rx in _NEWS:
        m = rx.search(t)
        if m:
            place = _clean_place(m.group("place"))
            if _GLOBAL_HINT.search(place or ""):
                return {"kind": "news", "global": True}
            if _valid(place):
                return {"kind": "news", "place": place}
    if _NEWS_GLOBAL.search(t):
        return {"kind": "news", "global": True}
    for rx in _LOCATE:
        m = rx.search(t)
        if m and _valid(_clean_place(m.group("place"))):
            return {"kind": "locate", "place": _clean_place(m.group("place"))}
    for rx in _KNOW:
        m = rx.search(t)
        if m:
            q = _clean_place(m.group("q"))
            if _valid(q):
                return {"kind": "knowledge", "query": q}
    return None


# ------------------------------------------------------------------ resolve

UI_ACKS = {"fullscreen": "Expanding, sir.", "minimize": "Minimising, sir.",
           "restore": "Restoring it, sir.", "close": "Closing that, sir."}


def resolve(text: str):
    """Return (messages, spoken, deferred) or None to defer to the brain.

    `messages` are broadcast immediately (camera + windows the user sees at
    once). `deferred` (or None) describes heavy enrichment the server runs in
    the background *while Jarvis is speaking* — the YouTube video and the
    worldwide fly-to — so it never adds voice-to-voice latency."""
    intent = parse_intent(text)
    if not intent:
        return None
    kind = intent["kind"]

    if kind == "ui":
        return ([{"type": "ui", "action": intent["action"]}],
                UI_ACKS.get(intent["action"], "Done, sir."), None)

    if kind == "knowledge":
        w = wikipedia(intent["query"])
        if not w:
            return None
        msgs = []
        if w.get("coords"):
            c = w["coords"]
            msgs.append({"type": "globe", "action": "focus", "lat": c["lat"],
                         "lng": c["lon"], "zoom": 1.7, "label": w["title"]})
        msgs.append({"type": "window", "kind": "wiki", "title": w["title"],
                     "extract": w["extract"], "thumb": w["thumb"], "url": w["url"]})
        spoken = w["extract"].split(". ")[0].strip() + "."
        return msgs, spoken, None

    if kind == "news" and intent.get("global"):
        items = news("world news breaking", limit=7)
        if not items:
            return None
        top = items[0]["title"]
        wid = _wid()
        cam = {"type": "globe", "action": "spin", "label": "Worldwide"}
        win = {"type": "window", "id": wid, "kind": "news", "title": "Worldwide",
               "items": items, "video_id": None}
        deferred = {"type": "worldwide", "window_id": wid, "title": top,
                    "video_query": top + " news"}
        return [cam, win], f"Top story worldwide, sir. {top}.", deferred

    if kind == "news":
        # Geocode and fetch headlines in parallel — neither needs the other.
        place = intent["place"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fg = ex.submit(geocode, place)
            fn = ex.submit(news, place, 6)
            g, items = fg.result(), fn.result()
        if not g or g["lat"] is None or not items:
            return None
        label = _label(g)
        wid = _wid()
        cam = {"type": "globe", "action": "focus", "lat": g["lat"], "lng": g["lng"],
               "zoom": 1.6, "label": label}
        win = {"type": "window", "id": wid, "kind": "news", "title": label,
               "items": items, "video_id": None}
        deferred = {"type": "video", "window_id": wid,
                    "query": f"{g['name']} {items[0]['title']}"}
        return [cam, win], f"Latest from {g['name']}, sir. {items[0]['title']}.", deferred

    g = geocode(intent["place"]) if intent.get("place") else None
    if not g or g["lat"] is None:
        return None
    label = _label(g)
    cam = {"type": "globe", "action": "focus", "lat": g["lat"], "lng": g["lng"],
           "label": label}

    if kind == "weather":
        w = weather(g["lat"], g["lng"])
        if not w:
            return None
        cam["zoom"] = 1.4
        win = {"type": "window", "kind": "weather", "title": label,
               "local_time": _local_time(w.get("timezone") or g.get("timezone")), **w}
        spoken = (f"It's {w['temp']} degrees and {w['desc'].lower()} in "
                  f"{g['name']}, sir, feeling like {w['feels']}.")
        return [cam, win], spoken, None

    if kind == "locate":
        cam["zoom"] = 1.4
        win = {"type": "window", "kind": "place", "title": label,
               "lat": round(g["lat"], 3), "lng": round(g["lng"], 3),
               "local_time": _local_time(g.get("timezone") or timezone_at(g["lat"], g["lng"])),
               "population": g.get("population"), "country": g.get("country")}
        lt = win["local_time"]
        return ([cam, win], f"Here's {g['name']}, sir." + (f" It's {lt} there." if lt else ""), None)

    return None
