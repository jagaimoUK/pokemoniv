#!/usr/bin/env python3
"""Event-aware PvPoke data update proposals. Does not deploy or modify user data."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "pvpoke_data_snapshot.py"
RECOMMENDATIONS = ROOT / "data/pvpoke_recommended_moves.json"
JST = ZoneInfo("Asia/Tokyo")
ICS = (
    "https://github.com/othyn/go-calendar/releases/latest/download/gocal__community_day.ics",
    "https://github.com/othyn/go-calendar/releases/latest/download/gocal__event.ics",
    "https://github.com/othyn/go-calendar/releases/latest/download/gocal__go_battle_league.ics",
    "https://github.com/othyn/go-calendar/releases/latest/download/gocal__season.ics",
)
PVP_API = "https://api.github.com/repos/pvpoke/pvpoke/commits/master"
PVP_RAW = "https://raw.githubusercontent.com/pvpoke/pvpoke/{commit}/src/{path}"
UPSTREAM = {
    "gamemaster.json": "data/gamemaster.json",
    "Pokemon.js": "js/pokemon/Pokemon.js",
    "rankings": "data/rankings/all/overall/rankings-1500.json",
}
MOVE_ID = re.compile(r"^[A-Z0-9_]{1,64}$")
SPECIES_ID = re.compile(r"^[a-z0-9_]{1,100}$")
CPMS_RE = re.compile(r"\bvar\s+cpms\s*=\s*\[([^\]]+)\]", re.S)


def download(url: str, limit: int = 12_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "pokemoniv-event-update/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Upstream response exceeded limit")
    return body


def unfold_ics(raw: str) -> list[str]:
    if not raw.startswith("BEGIN:VCALENDAR"):
        raise ValueError("Not an iCalendar document")
    result = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def parse_start(line: str) -> datetime | None:
    if not line.startswith("DTSTART"):
        return None
    head, sep, value = line.partition(":")
    if not sep:
        raise ValueError("Invalid DTSTART")
    tz_match = re.search(r"TZID=([^;:]+)", head)
    zone = ZoneInfo(tz_match.group(1)) if tz_match else JST
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").replace(tzinfo=zone)
    value = value.strip()
    if not re.fullmatch(r"\d{8}T\d{6}Z?", value):
        raise ValueError("Unexpected DTSTART encoding")
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone)


def read_event_starts(raw: bytes) -> list[dict]:
    lines = unfold_ics(raw.decode("utf-8-sig"))
    events, block = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            block = {}
        elif line == "END:VEVENT":
            if block and block.get("start"):
                events.append(block)
            block = None
        elif block is not None:
            if line.startswith("DTSTART"):
                block["start"] = parse_start(line)
            elif line.startswith("SUMMARY:"):
                block["name"] = line[8:][:160]
    if not events:
        raise ValueError("Calendar did not contain dated events")
    return events


def relevant_events(events: list[dict], now: datetime) -> list[dict]:
    """Checks around each event START, never continuously through a long season."""
    now = now.astimezone(JST)
    found = []
    for event in events:
        start = event["start"].astimezone(JST)
        delta = now - start
        if -timedelta(days=1) <= delta <= timedelta(days=2):
            found.append({"name": event.get("name", ""), "start_jst": start.isoformat()})
    return found


def eligible(now: datetime, event_lists: list[list[dict]], *, force=False) -> tuple[bool, list[dict]]:
    now = now.astimezone(JST)
    matches = relevant_events([e for group in event_lists for e in group], now)
    return force or now.weekday() == 0 or bool(matches), matches[:30]


def load_recommended(data: bytes, gm: dict) -> dict[str, list[str]]:
    entries = json.loads(data)
    if not isinstance(entries, list) or not 100 <= len(entries) <= 5000:
        raise ValueError("Invalid GL rankings length")
    pokemon = {p["speciesId"]: p for p in gm["pokemon"]}
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid rankings row")
        sid, moves = entry.get("speciesId"), entry.get("moveset")
        if not isinstance(sid, str) or not SPECIES_ID.fullmatch(sid):
            continue
        if not isinstance(moves, list) or len(moves) != 3 or not all(
            isinstance(m, str) and MOVE_ID.fullmatch(m) for m in moves
        ):
            continue
        species = pokemon.get(sid)
        if not species or moves[0] not in species["fastMoves"]:
            continue
        allowed = set(species["chargedMoves"])
        if "shadow" in species.get("tags", []):
            allowed.add("FRUSTRATION")
        if "shadoweligible" in species.get("tags", []):
            allowed.add("RETURN")
        if moves[1] == moves[2] or any(m not in allowed for m in moves[1:]):
            continue
        result[sid] = moves
    if len(result) < 100:
        raise ValueError("Too few valid GL recommendations")
    return dict(sorted(result.items()))


def validate_gm(data: bytes, pokemon_js: bytes) -> dict:
    gm = json.loads(data)
    if not isinstance(gm, dict) or not isinstance(gm.get("pokemon"), list) or not isinstance(gm.get("moves"), list):
        raise ValueError("Invalid GameMaster schema")
    if len(gm["pokemon"]) < 800 or len(gm["moves"]) < 200:
        raise ValueError("Suspiciously small GameMaster")
    ids = [m["moveId"] for m in gm["moves"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate move IDs")
    known = set(ids)
    species_ids = set()
    for p in gm["pokemon"]:
        sid = p["speciesId"]
        if sid in species_ids:
            raise ValueError("Duplicate species ID")
        species_ids.add(sid)
        if not set(p["fastMoves"] + p["chargedMoves"]).issubset(known):
            raise ValueError("Move reference missing in " + sid)
    match = CPMS_RE.search(pokemon_js.decode("utf-8"))
    if not match or not 90 <= len(match.group(1).split(",")) <= 200:
        raise ValueError("Unexpected Pokemon.js CPM array")
    return gm


def updated_snapshot(source: str, commit: str, sha: dict[str, str]) -> str:
    changed, n = re.subn(r"(?m)^COMMIT = '[0-9a-f]{40}'$",
                         f"COMMIT = '{commit}'", source)
    if n != 1:
        raise ValueError("Could not safely locate pinned commit")
    for filename, digest in (("gamemaster.json", sha["gamemaster.json"]),
                             ("Pokemon.js", sha["Pokemon.js"])):
        pattern = r"(?m)^    '" + re.escape(filename) + r"': \('([^']+)', '[0-9a-f]{64}'\),$"
        def replace(match, name=filename, value=digest):
            return f"    '{name}': ('{match.group(1)}', '{value}'),"
        changed, n = re.subn(pattern, replace, changed)
        if n != 1:
            raise ValueError("Could not safely locate pin: " + filename)
    return changed


def candidate(now: datetime, *, fetch=download) -> dict:
    """One coherent upstream revision; never replaces the running application's state."""
    commit = json.loads(fetch(PVP_API))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid upstream commit")
    data = {name: fetch(PVP_RAW.format(commit=commit, path=path))
            for name, path in UPSTREAM.items()}
    gm = validate_gm(data["gamemaster.json"], data["Pokemon.js"])
    recommended = load_recommended(data["rankings"], gm)
    sha = {key: hashlib.sha256(data[key]).hexdigest() for key in ("gamemaster.json", "Pokemon.js")}
    old_source = SNAPSHOT.read_text(encoding="utf-8")
    # Do not change the pinned source merely because upstream changed docs or UI.
    pins_match = all(
        ("'" + name + "': ('" + UPSTREAM[name] + "', '" + sha[name] + "')" in old_source)
        for name in ("gamemaster.json", "Pokemon.js")
    )
    new_source = old_source if pins_match else updated_snapshot(old_source, commit, sha)
    payload = {"schema": 1, "league": "great", "source_commit": commit,
               "source_sha256": hashlib.sha256(data["rankings"]).hexdigest(),
               "moves": recommended}
    raw_recommended = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    old_recommended = RECOMMENDATIONS.read_text(encoding="utf-8") if RECOMMENDATIONS.exists() else ""
    # Explicit verification target for the Nov 2026 Pawniard Community Day.
    kingambit = next((p for p in gm["pokemon"] if p.get("speciesId") == "kingambit"), None)
    kingambit_has_kowtow = bool(kingambit and
                                "KOWTOW_CLEAVE" in kingambit.get("chargedMoves", []))
    # Rankings may be re-generated without changing recommendations; avoid noisy proposals.
    old_moves = json.loads(old_recommended).get("moves") if old_recommended else None
    if old_moves == recommended:
        raw_recommended = old_recommended
    return {"changed": new_source != old_source or raw_recommended != old_recommended,
            "game_changed": new_source != old_source,
            "recommendations_changed": raw_recommended != old_recommended,
            "commit": commit, "recommended_count": len(recommended),
            "kingambit_has_kowtow_cleave": kingambit_has_kowtow,
            "kingambit_recommended": recommended.get("kingambit"),
            "snapshot_content": new_source, "recommendations_content": raw_recommended}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true", help="Stage generated source files in the current checkout")
    p.add_argument("--force", action="store_true", help="Bypass the event/weekly eligibility check")
    p.add_argument("--now", help="ISO-8601 test time, defaults to current UTC time")
    args = p.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        p.error("--now needs a timezone")
    calendars, errors = [], []
    for url in ICS:
        try:
            calendars.append(read_event_starts(download(url, 2_000_000)))
        except Exception as exc:
            errors.append({"calendar": url, "error": type(exc).__name__ + ": " + str(exc)[:200]})
    due, events = eligible(now, calendars, force=args.force)
    report = {"time_jst": now.astimezone(JST).isoformat(), "weekly": now.astimezone(JST).weekday() == 0,
              "events": events, "calendar_errors": errors, "due": due}
    if not due:
        if not calendars:
            print(json.dumps(report, ensure_ascii=False))
            return 2  # No calendar data means no reliable event detection.
        print(json.dumps(report, ensure_ascii=False))
        return 0
    result = candidate(now)
    report.update({k: result[k] for k in ("changed", "game_changed", "recommendations_changed",
                                          "commit", "recommended_count",
                                          "kingambit_has_kowtow_cleave", "kingambit_recommended")})
    if args.apply and result["changed"]:
        if result["game_changed"]:
            SNAPSHOT.write_text(result["snapshot_content"], encoding="utf-8")
        if result["recommendations_changed"]:
            RECOMMENDATIONS.parent.mkdir(parents=True, exist_ok=True)
            RECOMMENDATIONS.write_text(result["recommendations_content"], encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
