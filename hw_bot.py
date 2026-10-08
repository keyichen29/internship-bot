#!/usr/bin/env python3
"""
Hardware + product-management internship tracker.

Pulls three public GitHub internship lists, keeps only hardware-ish roles,
de-duplicates across them, remembers what it has already shown you, and writes:

  hardware_internships.md   everything currently open that matches
  seen.json                 memory of what you've already been pinged about

Notifies you on Discord (webhook) the moment a NEW matching role appears.
Also posts ONE "pick of the day" (most prestigious + best fit) to a second channel:  python hw_bot.py --daily
Run locally:   DISCORD_WEBHOOK_URL=... python hw_bot.py     (or  python hw_bot.py --test)
Run in cloud:  see .github/workflows/hw-bot.yml (runs every 5 minutes, free)
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# ----------------------------------------------------------------- CONFIG ---

SOURCES = {
    "jobright": "https://raw.githubusercontent.com/jobright-ai/2026-Engineer-Internship/master/README.md",
    "simplify": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
    "zshah": "https://raw.githubusercontent.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/main/README.md",
}

# A role is kept if its TITLE contains any of these (case-insensitive).
# Two buckets: hardware-ish roles and product/program-management roles.
HARDWARE_KEYWORDS = [
    "hardware", "robot", "embedded", "firmware", "fpga", "asic", "rtl", "soc ",
    "silicon", "mechatronic", "electrical", "electronics", "electronic", "pcb",
    "analog", "digital design", "verification", "circuit", "controls",
    "autonomy", "autonomous", "perception", "sensor",
    "manufacturing", "test engineer", "validation", "semiconductor", "vlsi",
    "layout", "power electronics", "rf ", "photonic", "optical", "gpu",
    "physical ai", "systems engineer", "thermal", "packaging", "reliability",
    "antenna", "wireless", "battery", "aerospace", "avionics", "propulsion",
    "design engineer", "npi", "new product introduction", "quality engineer",
    "industrial engineer", "devices", "instrumentation", "mems", "acoustic",
    "camera", "display", "chip", "device", "product engineer",
]

PM_KEYWORDS = [
    "product manag", "program manag", "product owner", "technical product",
    "product operations", "product analyst", "associate product", "apm",
    "technical program", "tpm", "product design", "product development",
]

# Set True to drop PM roles whose title says "software" (keeps hardware-adjacent PM only).
PM_SKIP_PURE_SOFTWARE = False

# Titles containing any of these are dropped (noise from the broad keywords).
EXCLUDE = [
    "marketing", "sales", "finance", "accounting", "legal", "hr ", "recruit",
    "civil", "environmental", "chemical", "biolog", "nurse", "clinical",
    "cyber", "devops", "data analyst", "customer success", "supply chain analyst",
    "mechanical", "mech eng",   # you asked to remove mechanical engineering roles entirely
]

# Optional: companies to star and sort first. Empty = no preference.
PRIORITY = []

# Simplify sections whose rows are ALL kept (no keyword needed).
SIMPLIFY_FORCE_SECTIONS = ["Hardware Engineering", "Product Management"]

# ---- "Pick of the day" settings -------------------------------------------
# Prestige score of the company (0-100). Matched as whole words, case-insensitive.
# Anything not listed gets DEFAULT_PRESTIGE. Edit freely: this is the main lever.
PRESTIGE_TIERS = {
    100: ["nvidia", "apple", "tesla", "spacex", "google", "alphabet", "deepmind", "waymo",
          "meta", "microsoft", "amazon", "boston dynamics", "anduril", "neuralink",
          "openai", "blue origin", "intuitive", "nasa", "jpl"],
    80: ["qualcomm", "amd", "intel", "broadcom", "samsung", "sony", "texas instruments",
         "analog devices", "micron", "marvell", "arm", "nxp", "lam research",
         "applied materials", "kla", "asml", "synopsys", "cadence", "lockheed", "northrop",
         "raytheon", "boeing", "ge aerospace", "general electric", "gm", "general motors",
         "ford", "toyota", "rivian", "lucid", "zoox", "nuro", "aurora", "skydio",
         "agility robotics", "apptronik", "1x", "joby", "archer", "rocket lab", "relativity",
         "medtronic", "stryker", "johnson & johnson", "abbott", "cisco", "bose", "honeywell",
         "siemens", "abb", "dyson", "garmin", "gopro", "oura", "irobot", "disney", "dell",
         "hp", "hewlett packard", "ibm"],
    60: ["john deere", "caterpillar", "cummins", "3m", "emerson", "eaton", "schneider",
         "bosch", "continental", "northrop grumman", "general dynamics", "l3harris",
         "collins aerospace", "pratt & whitney", "gulfstream", "sikorsky", "baxter", "bd",
         "philips", "medline", "whirlpool", "ge healthcare", "ge vernova"],
}
DEFAULT_PRESTIGE = 35

# Which companies count for the #prestige alert channel: 100 = top tier only, 80 = top two tiers.
PRESTIGE_ALERT_MIN = 100

# Optional personal fit tweaks. Leave empty for no preference.
BOOST_KEYWORDS = []         # e.g. ["robot", "embedded"]: +10 each if in the title (max +20)
PREFERRED_LOCATIONS = []    # e.g. ["CA", "Boston", "Seattle", "Remote"]: +8 if in the location

CORE_HW = ["hardware", "asic", "rtl", "fpga", "analog", "digital design", "vlsi", "silicon",
           "embedded", "firmware", "electrical", "mechatronic", "robot", "pcb",
           "circuit", "semiconductor", "photonic", "rf ", "power electronics", "controls",
           "avionics", "propulsion", "thermal", "optical", "verification", "soc "]
ADJ_HW = ["systems engineer", "test engineer", "validation", "manufacturing", "reliability",
          "packaging", "sensor", "autonom", "perception", "devices", "npi",
          "product development", "product engineer", "gpu", "chip", "wireless"]

HERE = Path(__file__).resolve().parent
SEEN_FILE = HERE / "seen.json"
ALL_FILE = HERE / "hardware_internships.md"
PICKS_FILE = HERE / "picks.json"

# ---------------------------------------------------------------- HELPERS ---


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "hw-intern-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " / ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # md links -> text
    s = s.replace("**", "").replace("🔥", "").replace("🛂", "").replace("🇺🇸", "")
    s = s.replace("🆕", "").replace("🆁", "").replace("🎓", "").replace("🔒", "").replace("✓", "")
    return re.sub(r"\s+", " ", s).strip(" |")


def norm_url(u: str) -> str:
    p = urlsplit(u)
    return urlunsplit((p.scheme, p.netloc, p.path.rstrip("/"), "", ""))


def make_key(company, title, url, location):
    if url:
        return norm_url(url)
    return f"{company.lower()}|{title.lower()}|{location.lower()}"


def category(title: str) -> str:
    t = " " + title.lower() + " "
    if any(k in t for k in PM_KEYWORDS):
        return "Product / Program Management"
    return "Hardware & Hardware-adjacent"


def matches(title: str, force: bool = False) -> bool:
    t = " " + title.lower() + " "
    if any(x in t for x in EXCLUDE):
        return False
    if category(title).startswith("Product"):
        if PM_SKIP_PURE_SOFTWARE and "software" in t:
            return False
        return force or any(k in t for k in PM_KEYWORDS)
    return force or any(k in t for k in HARDWARE_KEYWORDS)


def is_priority(company: str) -> bool:
    c = company.lower()
    return any(re.search(r"\b" + re.escape(p) + r"\b", c) for p in PRIORITY)


# ---------------------------------------------------------------- PARSERS ---


def parse_simplify(text: str):
    """HTML tables. The 'Hardware Engineering' section is auto-included; others keyword-filtered."""
    jobs = []
    # split by section heading
    sections = re.split(r"(?m)^## ", text)
    for sec in sections:
        header = sec.split("\n", 1)[0]
        in_hw = any(s in header for s in SIMPLIFY_FORCE_SECTIONS)
        last_company = ""
        for row in re.findall(r"<tr>(.*?)</tr>", sec, re.S):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            if len(cells) < 5:
                continue
            company = clean(cells[0])
            if company == "↳":
                company = last_company
            else:
                last_company = company
            title = clean(cells[1])
            loc = clean(cells[2])
            link = re.search(r'href="([^"]+)"', cells[3])
            url = link.group(1) if link else ""
            age = clean(cells[4])
            if "🔒" in cells[3] or not url:
                continue
            if matches(title, force=in_hw):
                jobs.append(dict(company=company, title=title, location=loc,
                                 url=url, posted=age, source="simplify"))
    return jobs


def parse_md_tables(text: str, source: str):
    """Markdown tables (jobright + zshah). Finds columns by header name."""
    jobs = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1]):
            header = [c.strip().lower() for c in lines[i].strip().strip("|").split("|")]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                i += 1
                if len(cells) != len(header):
                    continue
                row = dict(zip(header, cells))
                company = clean(row.get("company", ""))
                title_cell = row.get("job title") or row.get("role") or ""
                title = clean(title_cell)
                loc = clean(row.get("location", ""))
                posted = clean(row.get("date posted") or row.get("posted") or "")
                m = re.search(r"\]\((https?://[^)]+)\)", title_cell) or re.search(
                    r"\]\((https?://[^)]+)\)", row.get("apply", ""))
                url = m.group(1) if m else ""
                if company and title and matches(title):
                    jobs.append(dict(company=company, title=title, location=loc,
                                     url=url, posted=posted, source=source))
        else:
            i += 1
    return jobs


# ---------------------------------------------------------------- DISCORD ---

MAX_PER_RUN = 30  # most role cards posted in one run (the rest are summarized)
COLORS = {"HW": 0x2F81F7, "PM": 0xF0883E}


def sort_key(j):
    return (not is_priority(j["company"]), category(j["title"]),
            j["company"].lower(), j["title"].lower())


def discord_post(payload: dict, env: str = "DISCORD_WEBHOOK_URL") -> bool:
    url = os.environ.get(env, "").strip()
    if not url:
        return False
    data = json.dumps(payload).encode()
    for _ in range(5):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (hw-intern-bot, 1.0)"})  # Discord rejects the default Python UA
        try:
            with urllib.request.urlopen(req, timeout=30):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limited: wait as long as Discord asks, then retry
                try:
                    wait = float(json.loads(e.read()).get("retry_after", 2))
                except Exception:
                    wait = 2
                time.sleep(wait + 0.25)
                continue
            print(f"Discord error {e.code}: {e.read()[:200]!r}")
            return False
        except Exception as e:
            print(f"Discord error: {e}")
            time.sleep(2)
    return False


def embed(j):
    tag = "PM" if category(j["title"]).startswith("Product") else "HW"
    e = {
        "title": f"{j['company']}: {j['title']}"[:200],
        "description": f"📍 {(j['location'] or 'n/a')[:150]}\n🕒 {j['posted'] or 'n/a'}",
        "color": COLORS[tag],
        "footer": {"text": f"{'Product Mgmt' if tag == 'PM' else 'Hardware'} · via {j['source']}"},
    }
    if j["url"]:
        e["url"] = j["url"]
    return e


def is_pure_hardware(j) -> bool:
    """Hardware engineering only: a core-hardware word in the title, no PM, and not a software role."""
    t = " " + j["title"].lower() + " "
    return (not category(j["title"]).startswith("Product")
            and any(k in t for k in CORE_HW) and "software" not in t)


# Each route = one Discord channel (one webhook secret) + a rule for which new roles go there.
# A role can match several routes (e.g. a Google hardware role goes to hardware AND prestige).
ROUTES = {
    "hardware": dict(env="DISCORD_WEBHOOK_URL", label="hardware engineering",
                     match=is_pure_hardware, emoji="🔧", noun="hardware engineering"),
    "pm": dict(env="DISCORD_PM_WEBHOOK_URL", label="product / program management",
               match=lambda j: category(j["title"]).startswith("Product"), emoji="📋", noun="PM"),
    "prestige": dict(env="DISCORD_PRESTIGE_WEBHOOK_URL", label="top-tier companies",
                     match=lambda j: (prestige(j["company"]) >= PRESTIGE_ALERT_MIN
                                      and (is_pure_hardware(j) or category(j["title"]).startswith("Product"))),
                     emoji="🏆", noun="top-company"),
}


def notify_discord(new, route) -> bool:
    ordered = sorted(new, key=sort_key)
    batch = ordered[:MAX_PER_RUN]
    user = os.environ.get("DISCORD_USER_ID", "").strip()
    ping = f"<@{user}> " if user else ""
    n = len(new)
    head = f"{ping}{route['emoji']} **{n} new {route['noun']} internship{'s' if n != 1 else ''}**"
    if n > MAX_PER_RUN:
        head += f" (showing {MAX_PER_RUN}; full list is in `hardware_internships.md` in the repo)"
    for idx in range(0, len(batch), 10):
        ok = discord_post({
            "content": head if idx == 0 else "",
            "embeds": [embed(j) for j in batch[idx:idx + 10]],
            "allowed_mentions": {"parse": ["users"]},
        }, route["env"])
        if not ok:
            return False
        time.sleep(1)
    return True


# ------------------------------------------------------------ DAILY PICK ---


def prestige(company: str) -> int:
    c = company.lower()
    for score, names in sorted(PRESTIGE_TIERS.items(), reverse=True):
        if any(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", c) for n in names):
            return score
    return DEFAULT_PRESTIGE


def age_days(posted: str):
    p = (posted or "").strip().lower()
    m = re.match(r"(\d+)\s*d", p)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)\s*mo", p)
    if m:
        return int(m.group(1)) * 30
    now = datetime.now(timezone.utc)
    for fmt, add_year in (("%b %d, %Y", False), ("%b %d", True)):
        try:
            d = datetime.strptime(p.title() + (f" {now.year}" if add_year else ""),
                                  fmt + (" %Y" if add_year else "")).replace(tzinfo=timezone.utc)
            if d > now:  # "Dec 30" read in January means last year
                d = d.replace(year=d.year - 1)
            return max((now - d).days, 0)
        except Exception:
            continue
    return None


def score_job(j):
    """Returns (total_score, [reasons]). Prestige dominates; role fit breaks ties."""
    t = " " + j["title"].lower() + " "
    reasons = []
    pr = prestige(j["company"])
    if pr >= 100:
        reasons.append("top-tier brand")
    elif pr >= 80:
        reasons.append("big-name company")
    fit = 0
    has_core = any(k in t for k in CORE_HW)
    is_sw = "software" in t
    if category(j["title"]).startswith("Product"):
        fit += 24 + (6 if (has_core or "device" in t) else 0)
        reasons.append("product / program management")
    elif has_core and not is_sw:
        fit += 30
        reasons.append("core hardware role")
    elif has_core and is_sw:           # e.g. "Embedded Software Engineer": near hardware, but still software
        fit += 8
        reasons.append("software close to the hardware")
    elif any(k in t for k in ADJ_HW):
        fit += 15
        reasons.append("hardware-adjacent role")
    elif is_sw:
        fit -= 20
    boosts = [k for k in BOOST_KEYWORDS if k.lower() in t]
    if boosts:
        fit += min(10 * len(boosts), 20)
        reasons.append("matches your interests (" + ", ".join(boosts) + ")")
    if PREFERRED_LOCATIONS and any(l.lower() in j["location"].lower() for l in PREFERRED_LOCATIONS):
        fit += 8
        reasons.append("in a preferred location")
    a = age_days(j["posted"])
    if a is not None:
        fit += 10 if a <= 3 else 6 if a <= 14 else 2 if a <= 30 else -5 if a > 45 else 0
        if a <= 3:
            reasons.append("just posted")
    return pr + fit, reasons


def daily_pick(all_jobs):
    picks = json.loads(PICKS_FILE.read_text()) if PICKS_FILE.exists() else []
    done = {p["key"] for p in picks}
    pool = [(score_job(j), j) for k, j in all_jobs.items()
            if k not in done and (is_pure_hardware(j) or category(j["title"]).startswith("Product"))]
    if not pool:
        print("No unpicked roles available.")
        return 0
    pool.sort(key=lambda x: (-x[0][0], x[1]["company"].lower(), x[1]["title"].lower()))
    (score, reasons), j = pool[0]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user = os.environ.get("DISCORD_USER_ID", "").strip()
    ping = f"<@{user}> " if user else ""
    e = {
        "title": f"{j['company']}: {j['title']}"[:200],
        "description": (f"📍 {(j['location'] or 'n/a')[:150]}\n🕒 Posted: {j['posted'] or 'n/a'}\n\n"
                        f"**Why this one:** {', '.join(reasons) or 'best overall match today'}"),
        "color": 0xF1C40F,
        "footer": {"text": f"Pick of the day · {today} · via {j['source']}"},
    }
    if j["url"]:
        e["url"] = j["url"]
    payload = {"content": f"{ping}☀️ **Your one job for today.** If you're slammed, just do this one.",
               "embeds": [e], "allowed_mentions": {"parse": ["users"]}}
    have = bool(os.environ.get("DISCORD_DAILY_WEBHOOK_URL", "").strip())
    ok = discord_post(payload, "DISCORD_DAILY_WEBHOOK_URL") if have else True
    print(f"Pick ({score}): {j['company']} - {j['title']} [{', '.join(reasons)}]" +
          ("" if have else "  [no DISCORD_DAILY_WEBHOOK_URL set: not posted]"))
    if ok:
        picks.append({"key": j["key"], "date": today, "company": j["company"], "title": j["title"]})
        PICKS_FILE.write_text(json.dumps(picks, indent=1))
        return 0
    return 1


def collect():
    all_jobs, status = {}, []
    for name, url in SOURCES.items():
        try:
            text = fetch(url)
            jobs = parse_simplify(text) if name == "simplify" else parse_md_tables(text, name)
            status.append(f"{name}: {len(jobs)} matches")
            for j in jobs:
                k = make_key(j["company"], j["title"], j["url"], j["location"])
                if k in all_jobs:
                    all_jobs[k]["source"] += f"+{name}"
                else:
                    j["key"] = k
                    all_jobs[k] = j
        except Exception as e:  # keep going if one list is down
            status.append(f"{name}: FAILED ({e})")
    return all_jobs, status


# ------------------------------------------------------------------- MAIN ---


def main():
    if "--test-daily" in sys.argv:
        ok = discord_post({"content": "✅ hw-intern-bot test message: your daily-pick webhook works."},
                          "DISCORD_DAILY_WEBHOOK_URL")
        print("sent" if ok else "FAILED (check DISCORD_DAILY_WEBHOOK_URL)")
        return 0 if ok else 1
    if "--daily" in sys.argv:
        all_jobs, status = collect()
        print(" | ".join(status))
        return daily_pick(all_jobs)
    if "--test" in sys.argv:
        ok = discord_post({"content": "✅ hw-intern-bot test message: your webhook works."})
        print("sent" if ok else "FAILED (check DISCORD_WEBHOOK_URL)")
        return 0 if ok else 1

    all_jobs, status = collect()

    raw = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
    if raw and not all(isinstance(v, dict) for v in raw.values()):  # old single-list format
        raw = {r: dict(raw) for r in ROUTES}
    seen = {r: raw.get(r, {}) for r in ROUTES}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    summary = []
    for r, route in ROUTES.items():
        matching = [j for j in all_jobs.values() if route["match"](j)]
        new = [j for j in matching if j["key"] not in seen[r]]
        have = bool(os.environ.get(route["env"], "").strip())
        if r not in raw:
            # First time this channel exists: quietly learn what's open now, then say hello.
            for j in new:
                seen[r][j["key"]] = now
            if have and matching:
                discord_post({"content": f"✅ **hw-intern-bot is live in this channel** ({route['label']}). "
                                         f"Tracking {len(matching)} open roles. I'll ping you here when new ones appear."},
                             route["env"])
            summary.append(f"{r}: {len(matching)} open (seeded)" + ("" if have else " [no webhook]"))
        else:
            delivered = notify_discord(new, route) if (new and have) else True
            if delivered:  # if Discord failed, leave them unseen so the next run retries
                for j in new:
                    seen[r][j["key"]] = now
            summary.append(f"{r}: {len(matching)} open, {len(new)} new" + ("" if have else " [no webhook]"))

    ordered = sorted(all_jobs.values(), key=sort_key)
    lines = [f"# Hardware & product-management internships ({len(ordered)} open)\n"]
    for cat in ("Hardware & Hardware-adjacent", "Product / Program Management"):
        part = [j for j in ordered if category(j["title"]) == cat]
        if part:
            lines.append(f"## {cat} ({len(part)})\n")
            for j in part:
                link = f"[Apply]({j['url']})" if j["url"] else "(no link)"
                lines.append(f"- **{j['company']}**: {j['title']} · {j['location'] or 'n/a'} · "
                             f"{j['posted'] or ''} · {link} _({j['source']})_")
            lines.append("")
    ALL_FILE.write_text("\n".join(lines))
    SEEN_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True))

    print(" | ".join(status))
    print(f"{len(ordered)} total matches | " + " | ".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
