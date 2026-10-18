"""Scan the Wreckfest 2 dedicated-server game files for dropdown metadata.

Extracts human-readable titles (venues, layouts, weathers, AI sets) from the
game's binary property files. Titles are stored as a localization key followed
by a 4-byte little-endian length and the UTF-8 title bytes. Known quirk: a
trailing 't' is sometimes corrupted into a non-letter byte (checksum artifact);
we repair that.
"""

from __future__ import annotations

import re
from pathlib import Path

# Localization key prefixes used by the game for each property type.
_KEY_VENUE = b"ENVIRONMENT_TITLE"
_KEY_LAYOUT = b"EVENT_TITLE"
_KEY_WEATHER = b"WEATHER_NAME"
_KEY_AISET = b"VEHICLE_AI_SET_NAME"

# Virtual AI sets referenced by community configs; not present as files on disk.
VIRTUAL_AI_SETS = [
    ("career/ai-class-all.aist", "All classes"),
    ("career/ai-class-a.aist", "Class A"),
    ("career/ai-class-b.aist", "Class B"),
    ("career/ai-class-c.aist", "Class C"),
    ("career/ai-class-d.aist", "Class D"),
]

GAME_MODES = [
    ("", "Game default"),
    ("bangerrace", "Banger Race (laps)"),
    ("derby", "Derby"),
    ("deathmatch", "Deathmatch"),
    ("folkrace", "Folk Race"),
    ("suiciderace", "Suicide Race"),
    ("waypointrace", "Waypoint Race"),
]

RULES_FLAGS = [
    "disable car resets",
    "disable wrong way limiter",
    "disable off board camera",
    "disable class a",
    "disable class b",
    "disable class c",
    "disable class d",
    "disable upgrades",
    "disable tuning",
]

SERVER_FLAGS = [
    "leader enabled",
    "idle kicker disabled",
]

VEHICLE_DAMAGE_IDS = [
    ("", "Game mode default"),
    ("normal", "Normal"),
    ("realistic", "Realistic"),
    ("damage_race", "Race damage"),
    ("damage_derby", "Derby damage"),
]

START_ORDERS = [
    "random",
    "points",
    "points reversed",
    "last race reversed",
]

# Venues whose localization bytes are mangled beyond repair; curated manually.
VENUE_OVERRIDES = {
    "track05": "European Rallycross",
}


def _extract_title(data: bytes, key: bytes) -> str | None:
    i = data.find(key)
    if i < 0:
        return None
    j = i
    while j < len(data) and 32 <= data[j] < 127:
        j += 1
    if j + 4 > len(data):
        return None
    n = int.from_bytes(data[j : j + 4], "little")
    if n <= 0 or j + 4 + n > len(data):
        return None
    raw = data[j + 4 : j + 4 + n]
    # Repair the trailing-'t' corruption quirk: last byte checksum-mangles 't'
    # into a random non-letter (e.g. "Defaul0", "Sunse/"). Known stems get 't'
    # appended regardless of the stray byte; other strings ending in a
    # non-letter get the byte stripped, while digits ("Deathloop 2") are kept.
    if raw:
        last = raw[-1]
        is_letter = 65 <= last <= 90 or 97 <= last <= 122
        if not is_letter:
            if raw[:-1].endswith(
                (b"Defaul", b"Sunse", b"Circuit Shor", b"Dirt Ova", b"Figure ", b"Mud Ova")
            ):
                raw = raw[:-1] + b"t"
            elif not (48 <= last <= 57):
                raw = raw[:-1]
    try:
        title = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    # Titles containing control/garbled bytes are unusable.
    if not re.fullmatch(r"[A-Za-z0-9 '\-&,!\(\)\.]+", title):
        return None
    return title


def _scan_event_dirs(game_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (venue titles by trackNN, layout titles by full level id)."""
    venues: dict[str, str] = {}
    layouts: dict[str, str] = {}
    event_root = game_dir / "data" / "property" / "event"
    if not event_root.is_dir():
        return venues, layouts
    for envi in sorted(event_root.glob("track*/*.envi")):
        title = _extract_title(envi.read_bytes(), _KEY_VENUE)
        if not title:
            title = VENUE_OVERRIDES.get(envi.stem)
        if title:
            venues[envi.stem] = title
    for evse in sorted(event_root.glob("track*/*.evse")):
        title = _extract_title(evse.read_bytes(), _KEY_LAYOUT)
        if title:
            layouts[evse.stem] = title
    return venues, layouts


def _scan_weathers(game_dir: Path) -> list[dict]:
    root = game_dir / "data" / "property" / "weather"
    out: list[dict] = []
    if not root.is_dir():
        return out
    for f in sorted(root.glob("*.weat")):
        title = _extract_title(f.read_bytes(), _KEY_WEATHER) or f.stem
        out.append(
            {
                "id": f"data/property/weather/{f.name}",
                "name": title,
                "stem": f.stem,
            }
        )
    return out


def _scan_ai_sets(game_dir: Path) -> list[dict]:
    out: list[dict] = [
        {"id": path, "name": name, "virtual": True} for path, name in VIRTUAL_AI_SETS
    ]
    root = game_dir / "data" / "property" / "career" / "ai_sets"
    if root.is_dir():
        for f in sorted(root.glob("*.aist")):
            title = _extract_title(f.read_bytes(), _KEY_AISET) or f.stem
            # Configs reference these as career/<name>.aist
            out.append({"id": f"career/{f.stem}.aist", "name": title, "virtual": False})
        singles = root / "singles"
        if singles.is_dir():
            for f in sorted(singles.glob("*.aist")):
                title = _extract_title(f.read_bytes(), _KEY_AISET) or f.stem
                out.append(
                    {
                        "id": f"career/singles/{f.stem}.aist",
                        "name": f"{title} (single car)",
                        "virtual": False,
                    }
                )
    return out


def _weather_group(stem: str, level_id: str) -> bool:
    """Heuristic: does a weather file plausibly belong to a level's venue?"""
    if stem in ("default",) or stem.startswith("menu"):
        return True
    venue = re.match(r"(track\d+)", level_id)
    if venue and stem.startswith(venue.group(1)):
        return True
    # Known cross-references from the shipped configs.
    sandpit = {"track02"}
    if venue and venue.group(1) in sandpit and stem.startswith("sandpit"):
        return True
    # track12 events reference track12_* weathers only; keep generic otherwise.
    return False


def scan_game_data(game_dir: Path) -> dict:
    venues, layouts = _scan_event_dirs(game_dir)
    weathers = _scan_weathers(game_dir)
    ai_sets = _scan_ai_sets(game_dir)

    # Authoritative level-id list: layout directories in art/levels.
    level_ids: list[str] = []
    art_levels = game_dir / "data" / "art" / "levels"
    if art_levels.is_dir():
        level_ids = sorted(
            d.name for d in art_levels.iterdir() if d.is_dir() and d.name.startswith("track")
        )

    tracks: list[dict] = []
    for lid in level_ids:
        venue_key = lid.split("_")[0]
        venue = venues.get(venue_key, venue_key)
        layout = layouts.get(lid)
        if layout:
            display = f"{venue} – {layout}"
        else:
            display = venue if venue != venue_key else lid
        rev = lid.endswith("_rev")
        tracks.append(
            {
                "id": lid,
                "venue": venue,
                "layout": layout or "",
                "display": display,
                "reverse": rev,
                "weathers": [
                    w["id"]
                    for w in weathers
                    if _weather_group(w["stem"], lid)
                ],
            }
        )

    return {
        "tracks": tracks,
        "weathers": weathers,
        "ai_sets": ai_sets,
        "game_modes": [{"id": i, "name": n} for i, n in GAME_MODES],
        "rules_flags": RULES_FLAGS,
        "server_flags": SERVER_FLAGS,
        "vehicle_damage_ids": [{"id": i, "name": n} for i, n in VEHICLE_DAMAGE_IDS],
        "start_orders": START_ORDERS,
    }
