#!/usr/bin/env python3
"""Fetch course facts from TISS and write them as Jekyll data files.

Usage:
    python3 tools/fetch_tiss.py 2026W            # both courses
    python3 tools/fetch_tiss.py 2026W --course sep

Writes _data/courses/<slug>/<semester>.yml, which Jekyll exposes to the pages as
site.data.courses[<slug>][<semester>].

Two sources are combined, because neither is complete on its own:

  * the REST API (https://tiss.tuwien.ac.at/api/course/<nr>-<semester>) for the
    structured metadata -- title, ECTS, hours, language, TUWEL link;
  * the public course page for teaching staff, dates and registration periods,
    which the API does not expose.

The public page bootstraps a DeltaSpike window id in JavaScript, so it cannot be
fetched naively -- see _handshake_get() below.

Standard library only; no pip install required.
"""

import argparse
import datetime
import html
import pathlib
import random
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar

COURSES = {
    "sep": {"nr": "194148", "pretty": "194.148"},
    "ase": {"nr": "188910", "pretty": "188.910"},
}

BASE = "https://tiss.tuwien.ac.at"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NS = {
    "c": "https://tiss.tuwien.ac.at/api/schemas/course/v10",
    "i": "https://tiss.tuwien.ac.at/api/schemas/i18n/v10",
}


class TissError(RuntimeError):
    pass


# --------------------------------------------------------------------------- fetch

def _handshake_get(url):
    """GET a TISS page, replicating the client-side window-id bootstrap.

    windowIdHandling.js generates a request token and a window id, stores a
    cookie `dsrwid-<token>` = <windowId>, then reloads the page with matching
    `dsrid` and `dswid` query parameters. Without that round trip every request
    returns a "Something went seriously wrong" placeholder. Any pair of numbers
    works as long as cookie and parameters agree.
    """
    rid = random.randint(100, 999)
    wid = random.randint(1000, 9999)

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    opener.addheaders = [("User-Agent", UA)]

    opener.open(url, timeout=30).read()  # first hit: establish the session

    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}dsrid={rid}&dswid={wid}")
    req.add_header("Cookie", f"dsrwid-{rid}={wid}")
    body = opener.open(req, timeout=30).read().decode("utf-8", "replace")

    if "seriously wrong" in body or "<title>Loading" in body:
        raise TissError(f"TISS returned its bootstrap placeholder for {url}")
    return body


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/xml"})
    return urllib.request.urlopen(req, timeout=30).read()


# --------------------------------------------------------------------------- parse

def _strip(fragment):
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _section(page, heading):
    """Return the HTML between <h2>heading</h2> and the next <h2>."""
    m = re.search(rf"<h2[^>]*>\s*{re.escape(heading)}\s*</h2>", page)
    if not m:
        return None
    rest = page[m.end():]
    nxt = re.search(r"<h2[^>]*>", rest)
    return rest[: nxt.start()] if nxt else rest


def _rows(section_html):
    """Parse a table's body rows into lists of cell strings."""
    body = re.search(r"<tbody\b.*?</tbody>", section_html, re.S)
    scope = body.group(0) if body else section_html
    out = []
    for tr in re.findall(r"<tr\b.*?</tr>", scope, re.S):
        if "<th" in tr:
            continue
        cells = [_strip(td) for td in re.findall(r"<td\b.*?</td>", tr, re.S)]
        if any(cells):
            out.append(cells)
    return out


def parse_staff(page):
    section = _section(page, "Vortragende Personen")
    if section is None:
        raise TissError("no 'Vortragende Personen' heading found")
    people = []
    for href, label in re.findall(
        r'<a href="([^"]*adressbuch/person/[^"]*)"[^>]*>(.*?)</a>', section, re.S
    ):
        label = _strip(label)
        if not label:
            continue
        # TISS renders "Surname, Given" -- flip to reading order for the page.
        display = " ".join(p.strip() for p in reversed(label.split(","))).strip()
        people.append({"name": display, "sorted": label, "url": html.unescape(href)})
    if not people:
        raise TissError("'Vortragende Personen' section contained no people")
    return people


def parse_dates(page):
    section = _section(page, "LVA Termine")
    if section is None:
        return []
    dates = []
    for cells in _rows(section):
        if len(cells) < 4:
            continue
        day, time, date, room = cells[0], cells[1], cells[2], cells[3]
        dates.append({
            "day": day,
            "time": time,
            "date": date,
            "room": room,
            "description": cells[4] if len(cells) > 4 else "",
        })
    return dates


def parse_exams(page):
    section = _section(page, "Prüfungen")
    if section is None:
        return []
    exams = []
    for cells in _rows(section):
        if len(cells) < 4:
            continue
        exams.append({
            "day": cells[0],
            "time": cells[1],
            "date": cells[2],
            "room": cells[3],
            "description": cells[-1],
        })
    return exams


def parse_characteristics(page):
    """ECTS and delivery format live only in the page's 'Merkmale' block."""
    section = _section(page, "Merkmale")
    if section is None:
        return {}
    text = _strip(section)
    out = {}
    for key, pattern in (("ects", r"ECTS:\s*([\d.,]+)"),
                         ("format", r"Format der Abhaltung:\s*([A-Za-z\u00c0-\u017f ]+)")):
        m = re.search(pattern, text)
        if m:
            out[key] = m.group(1).strip()
    return out


def parse_registration(page):
    section = _section(page, "LVA-Anmeldung")
    if section is None:
        return None
    rows = _rows(section)
    if not rows:
        return None
    cells = rows[0]
    if len(cells) < 3:
        raise TissError(f"unexpected LVA-Anmeldung row: {cells!r}")
    return {"from": cells[0], "to": cells[1], "deregistration_until": cells[2]}


def parse_api(course_nr, semester):
    raw = _get(f"{BASE}/api/course/{course_nr}-{semester}")
    course = ET.fromstring(raw).find("c:course", NS)
    if course is None:
        raise TissError(f"no course record for {course_nr}-{semester}")

    def text(tag):
        el = course.find("c:" + tag, NS)
        return (el.text or "").strip() if el is not None and el.text else None

    def i18n(tag, lang):
        el = course.find(f"c:{tag}/i:{lang}", NS)
        return (el.text or "").strip() if el is not None and el.text else None

    return {
        "title": i18n("title", "de"),
        "title_en": i18n("title", "en"),
        "type": text("courseType"),
        "weekly_hours": text("weeklyHours"),
        "language": i18n("language", "de"),
        "language_en": i18n("language", "en"),
        "institute_code": text("instituteCode"),
        "institute": i18n("instituteName", "de"),
        "institute_en": i18n("instituteName", "en"),
        "tuwel": text("eLearning"),
    }


# --------------------------------------------------------------------------- emit

def _scalar(value):
    if value is None:
        return '""'
    text = str(value)
    if text == "":
        return '""'
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_yaml(data, indent=0):
    pad = "  " * indent
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(to_yaml(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                lines.append(f"{pad}{key}: []")
                continue
            lines.append(f"{pad}{key}:")
            for item in value:
                if isinstance(item, dict):
                    inner = to_yaml(item, indent + 2).splitlines()
                    first = inner[0].strip()
                    lines.append(f"{pad}  - {first}")
                    lines.extend(inner[1:])
                else:
                    lines.append(f"{pad}  - {_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_scalar(value)}")
    return "\n".join(lines)


def build(slug, semester):
    meta = COURSES[slug]
    page_url = (f"{BASE}/course/courseDetails.xhtml"
                f"?courseNr={meta['nr']}&semester={semester}")
    page = _handshake_get(page_url)

    record = {
        "generated_by": "tools/fetch_tiss.py",
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": page_url,
        "course_number": meta["pretty"],
        "semester": semester,
    }
    record.update(parse_api(meta["nr"], semester))
    record.update(parse_characteristics(page))
    record["tiss"] = page_url
    record["staff"] = parse_staff(page)
    registration = parse_registration(page)
    if registration:
        record["registration"] = registration
    record["dates"] = parse_dates(page)
    exams = parse_exams(page)
    if exams:
        record["exams"] = exams
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("semester", help="TISS semester code, e.g. 2026W or 2027S")
    ap.add_argument("--course", choices=sorted(COURSES), action="append",
                    help="limit to one course (repeatable); default: all")
    ap.add_argument("--out", default="_data/courses",
                    help="output directory (default: _data/courses)")
    args = ap.parse_args()

    if not re.fullmatch(r"\d{4}[WS]", args.semester):
        ap.error("semester must look like 2026W or 2027S")

    failures = 0
    for slug in (args.course or sorted(COURSES)):
        try:
            record = build(slug, args.semester)
        except (TissError, OSError, ET.ParseError) as exc:
            print(f"  {slug} {args.semester}: FAILED -- {exc}", file=sys.stderr)
            failures += 1
            continue

        path = pathlib.Path(args.out) / slug / f"{args.semester}.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# Generated by tools/fetch_tiss.py -- do not edit by hand.\n"
            f"# Re-run: python3 tools/fetch_tiss.py {args.semester} --course {slug}\n"
            + to_yaml(record) + "\n",
            encoding="utf-8",
        )
        print(f"  {path}  ({len(record['staff'])} staff, "
              f"{len(record['dates'])} dates, "
              f"{len(record.get('exams', []))} exam slots)")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
