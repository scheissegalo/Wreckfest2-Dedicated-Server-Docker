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

# Valid AI set ids for the current build (adapts to whichever layout ships);
# only used to seed the dropdown when the game files are not on disk.
FALLBACK_AI_SETS = ["data/property/career/ai_sets/racing.aist"]

# Game mode ids referenced by shipped event loops. Modes with no exact match use
# the empty string, which makes the game use the event's intrinsic mode.
GAME_MODES = [
    ("", "Event default"),
    ("bangerrace", "Banger Race (laps)"),
    ("derby", "Derby"),
    ("deathmatch", "Deathmatch"),
    ("folkrace", "Folk Race"),
    ("suiciderace", "Suicide Race"),
    ("waypointrace", "Waypoint Race"),
]

# Event loop that drives the level/AI-set scan when none is shipped as a plain
# file (refuses to match obfuscated .qred data).
_REF_LOOP = "default_event_rotation.becl"

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


_GAMEMODE_RE = re.compile(rb"gamemode/([a-z_]+)")


def _scan_event_dirs(
    game_dir: Path,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], set[str]]:
    """Return (venue titles, layout titles, default modes, event level ids).

    The level's intrinsic game mode is stored in its .evse as a
    ``gamemode/<id>`` reference (e.g. ``gamemode/suiciderace``). Levels without
    such a reference are normal race levels (empty mode). ``event_levels`` is
    every level that ships an .evse (i.e. is a playable event), including the
    mode levels whose title cannot be extracted.
    """
    venues: dict[str, str] = {}
    layouts: dict[str, str] = {}
    default_modes: dict[str, str] = {}
    event_levels: set[str] = set()
    event_root = game_dir / "data" / "property" / "event"
    if not event_root.is_dir():
        return venues, layouts, default_modes, event_levels
    for envi in sorted(event_root.glob("track*/*.envi")):
        title = _extract_title(envi.read_bytes(), _KEY_VENUE)
        if not title:
            title = VENUE_OVERRIDES.get(envi.stem)
        if title:
            venues[envi.stem] = title
    for evse in sorted(event_root.glob("track*/*.evse")):
        data = evse.read_bytes()
        event_levels.add(evse.stem)
        title = _extract_title(data, _KEY_LAYOUT)
        if title:
            layouts[evse.stem] = title
        m = _GAMEMODE_RE.search(data)
        if m:
            default_modes[evse.stem] = m.group(1).decode("ascii")
    return venues, layouts, default_modes, event_levels


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


_REF_AI_RE = re.compile(rb"(data/property/career/ai_sets/[A-Za-z0-9_/]+\.aist)")
_REF_PAREN_RE = re.compile(rb"[\x20-\x7e]{2,}")


def _scan_ai_sets(game_dir: Path) -> list[dict]:
    found: set[str] = set(_scan_ai_set_ids(game_dir))
    for loop in _iter_reference_loops(game_dir):
        found.update(
            m.decode("ascii") for m in _REF_AI_RE.findall(loop.read_bytes())
        )
    if not found:
        found.update(FALLBACK_AI_SETS)
    out: list[dict] = [
        {"id": path, "name": _ai_set_name(path), "virtual": False}
        for path in sorted(found)
    ]
    return out


def _scan_ai_set_ids(game_dir: Path) -> list[str]:
    """Every AI set shipped on disk, id'd by its own path.

    The racing sets (``racing``/``fwd``/``rwd``/``muscle``/…) and per-car
    ``singles`` sets are valid but only some are referenced by the shipped
    loops, so enumerate the files too. Ids use the ``data/property/career/``
    prefix the game expects in configs.
    """
    out: list[str] = []
    root = game_dir / "data" / "property" / "career" / "ai_sets"
    if not root.is_dir():
        return out
    for f in sorted(root.glob("*.aist")):
        out.append(f"data/property/career/ai_sets/{f.name}")
    for sub in ("singles", "quickchallenge"):
        subdir = root / sub
        if subdir.is_dir():
            for f in sorted(subdir.glob("*.aist")):
                out.append(f"data/property/career/ai_sets/{sub}/{f.name}")
    return out


def _ai_set_name(path: str) -> str:
    stem = path.rsplit(".", 1)[0].rsplit("/", 1)[-1]
    return stem.replace("_", " ").strip().title()


def _iter_reference_loops(game_dir: Path) -> list[Path]:
    """Event-loop files to mine for valid ids (the one we build against)."""
    settings = game_dir / "data" / "property" / "settings"
    found: list[Path] = []
    ref = settings / _REF_LOOP
    if ref.is_file():
        found.append(ref)
    if settings.is_dir():
        for f in sorted(settings.glob("*.becl")):
            if f != ref:
                found.append(f)
    cup = settings / "cup"
    if cup.is_dir():
        found.extend(sorted(cup.glob("*.becl")))
    return found


def _reference_level_ids(game_dir: Path) -> list[str]:
    """Level ids referenced by the shipped reference loop, in file order."""
    ref = game_dir / "data" / "property" / "settings" / _REF_LOOP
    if not ref.is_file():
        return []
    ids: list[str] = []
    for m in _REF_PAREN_RE.finditer(ref.read_bytes()):
        s = m.group().decode("latin-1")
        if re.fullmatch(r"track\d+_\d+(?:_rev)?", s) and s not in ids:
            ids.append(s)
    return ids


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
    venues, layouts, default_modes, event_levels = _scan_event_dirs(game_dir)
    weathers = _scan_weathers(game_dir)
    ai_sets = _scan_ai_sets(game_dir)

    mode_names = dict(GAME_MODES)

    # Level-id list: layout dirs in art/levels, plus every level that ships an
    # .evse event (the mode levels have no art dir but are part of the game's
    # default rotation).
    level_ids: set[str] = set()
    art_levels = game_dir / "data" / "art" / "levels"
    if art_levels.is_dir():
        level_ids |= {
            d.name for d in art_levels.iterdir() if d.is_dir() and d.name.startswith("track")
        }
    level_ids |= event_levels
    level_ids |= set(_reference_level_ids(game_dir))

    tracks: list[dict] = []
    for lid in sorted(level_ids):
        venue_key = lid.split("_")[0]
        venue = venues.get(venue_key, venue_key)
        layout = layouts.get(lid)
        mode = default_modes.get(lid, "")
        if layout:
            display = f"{venue} – {layout}"
        elif mode:
            display = f"{venue} – {mode_names.get(mode, mode)}"
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
                "has_event": lid in event_levels,
                "default_mode": mode,
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
