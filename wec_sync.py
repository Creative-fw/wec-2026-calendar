#!/usr/bin/env python3
"""
FIA WEC 2026 -> corrected, auto-updating ICS feed.

Fetches the official fiawec.com per-race calendar endpoints, repairs two
known bugs in their feed, merges everything into one subscribable .ics:

  Bug 1: End times for non-European rounds are double-converted through
         Europe/Paris (e.g. Fuji's 6h race "ends" 13h after start).
         Fix: end_real = end_stored - (track_offset - paris_offset).
         Self-healing: correction only applied if it yields a sane positive
         duration; if FIA fixes their feed, raw values pass through.

  Bug 2: Le Mans events are local (Paris) wall times mislabeled as UTC (Z).
         Fix: reinterpret Z timestamps from these endpoints as Europe/Paris.
"""
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
BASE = "https://www.fiawec.com/en/race/calendar/{}"

# (endpoint_id, round_label, location)
ROUNDS = [
    (5042, "Prologue - Imola",      "Autodromo Enzo e Dino Ferrari, Imola, Italy"),
    (4948, "6H Imola",              "Autodromo Enzo e Dino Ferrari, Imola, Italy"),
    (4949, "6H Spa-Francorchamps",  "Circuit de Spa-Francorchamps, Belgium"),
    (4950, "Le Mans Test Day",      "Circuit de la Sarthe, Le Mans, France"),
    (4951, "24H Le Mans",           "Circuit de la Sarthe, Le Mans, France"),
    (4952, "6H Sao Paulo",          "Autodromo Jose Carlos Pace (Interlagos), Sao Paulo, Brazil"),
    (4953, "Lone Star Le Mans",     "Circuit of The Americas, Austin, Texas, USA"),
    (4954, "6H Fuji",               "Fuji Speedway, Oyama, Japan"),
    (4947, "Qatar 1812km",          "Lusail International Circuit, Lusail, Qatar"),
    (4955, "8H Bahrain",            "Bahrain International Circuit, Sakhir, Bahrain"),
    (4956, "Rookie Test - Bahrain", "Bahrain International Circuit, Sakhir, Bahrain"),
]

MAX_SANE = {"24h le mans - race": 24.5, "default_race": 11.0, "default": 5.0}

VTZ = """BEGIN:VTIMEZONE
TZID:Europe/Paris
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Europe/Rome
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:America/Sao_Paulo
BEGIN:STANDARD
TZOFFSETFROM:-0300
TZOFFSETTO:-0300
TZNAME:-03
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:America/Chicago
BEGIN:DAYLIGHT
TZOFFSETFROM:-0600
TZOFFSETTO:-0500
TZNAME:CDT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0500
TZOFFSETTO:-0600
TZNAME:CST
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Asia/Tokyo
BEGIN:STANDARD
TZOFFSETFROM:+0900
TZOFFSETTO:+0900
TZNAME:JST
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Asia/Qatar
BEGIN:STANDARD
TZOFFSETFROM:+0300
TZOFFSETTO:+0300
TZNAME:+03
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE
BEGIN:VTIMEZONE
TZID:Asia/Bahrain
BEGIN:STANDARD
TZOFFSETFROM:+0300
TZOFFSETTO:+0300
TZNAME:+03
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE"""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (wec-ics-sync)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_events(ics_text):
    """Yield (summary, dtstart_raw, dtend_raw, tzid_or_None_for_Z)."""
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_text, re.S):
        m_sum = re.search(r"SUMMARY:(.+)", block)
        m_st = re.search(r"DTSTART(?:;TZID=([^:]+))?:(\d{8}T\d{6})(Z?)", block)
        m_en = re.search(r"DTEND(?:;TZID=([^:]+))?:(\d{8}T\d{6})(Z?)", block)
        if not (m_sum and m_st and m_en):
            continue
        tzid = m_st.group(1)  # None when Z-stamped
        yield (m_sum.group(1).strip().rstrip("\r"), m_st.group(2), m_en.group(2), tzid)


def repair(summary, start_s, end_s, tzid):
    """Return (start_dt_naive, end_dt_naive, tzid) with bugs fixed."""
    if tzid is None:
        tzid = "Europe/Paris"  # Bug 2: Z timestamps are Paris wall time
    tz = ZoneInfo(tzid)
    start = datetime.strptime(start_s, "%Y%m%dT%H%M%S")
    end = datetime.strptime(end_s, "%Y%m%dT%H%M%S")

    # Bug 1: undo Paris<->track double conversion on DTEND
    diff = tz.utcoffset(start) - PARIS.utcoffset(start.replace(tzinfo=None))
    if diff != timedelta(0):
        corrected = end - diff
        s_low = summary.lower()
        cap = MAX_SANE["default_race"] if "race" in s_low else MAX_SANE["default"]
        raw_dur = (end - start).total_seconds() / 3600
        cor_dur = (corrected - start).total_seconds() / 3600
        # prefer correction when it is sane; fall back to raw if FIA fixed feed
        if 0 < cor_dur <= cap and not (0 < raw_dur <= cap and cor_dur > raw_dur):
            end = corrected
    if end <= start:  # last-resort guard: never emit invalid events
        end = start + timedelta(hours=1)
    return start, end, tzid


def esc(s):
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def main(out_path):
    events = []
    for cal_id, label, loc in ROUNDS:
        try:
            text = fetch(BASE.format(cal_id))
        except Exception as e:
            print(f"WARN: round '{label}' (id {cal_id}) fetch failed: {e}", file=sys.stderr)
            continue
        for summary, st, en, tzid in parse_events(text):
            # strip duplicated event name prefix, keep session name only
            session = re.sub(r"^.*? - ", "", summary) if " - " in summary else summary
            start, end, tz = repair(summary, st, en, tzid)
            is_race = session.strip().lower() == "race" or "race" in session.lower()
            events.append((start, end, tz, label, session, loc, is_race))

    if len(events) < 30:
        print(f"ABORT: only {len(events)} events fetched - refusing to overwrite feed.",
              file=sys.stderr)
        sys.exit(1)

    events.sort(key=lambda e: (e[0], e[3]))
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//LGS//FIA WEC 2026 Auto-Sync//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:FIA WEC 2026",
             "X-WR-CALDESC:FIA WEC 2026 - auto-synced daily from fiawec.com official feed",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
             "X-PUBLISHED-TTL:PT12H"]
    lines += VTZ.split("\n")

    for i, (start, end, tz, label, session, loc, is_race) in enumerate(events, 1):
        flag = "\U0001F3C1 " if is_race else ""
        uid = re.sub(r"[^a-z0-9]+", "-", f"{label}-{session}".lower()).strip("-")
        lines += ["BEGIN:VEVENT",
                  f"UID:{uid}@lgs-fiawec-2026",
                  f"DTSTAMP:{now}",
                  f"DTSTART;TZID={tz}:{start.strftime('%Y%m%dT%H%M%S')}",
                  f"DTEND;TZID={tz}:{end.strftime('%Y%m%dT%H%M%S')}",
                  f"SUMMARY:{esc(flag + 'WEC ' + label + ' - ' + session)}",
                  f"LOCATION:{esc(loc)}",
                  "DESCRIPTION:Track-local time. Auto-synced from fiawec.com. "
                  "Live: https://plus.fiawec.com"]
        if is_race:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY",
                      f"DESCRIPTION:{esc(label)} race starts in 1 hour",
                      "TRIGGER:-PT1H", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")

    with open(out_path, "w", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    print(f"OK: wrote {len(events)} events -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "FIA_WEC_2026.ics")
