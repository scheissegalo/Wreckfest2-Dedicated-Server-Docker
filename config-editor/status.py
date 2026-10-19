"""Parse the wrapper's server.log into a live dashboard snapshot.

The upstream wrapper tees the game console into ``server.log``. Its output
is noisy: every received fragment gets a wrapper timestamp prefix, long
messages are split mid-word across lines (``...track01_1_`` + ``rev)``),
and a duplicated block can appear after a log-writer restart.
``parse_server_log`` normalises all of that and reduces the stream to what
a server admin cares about: who is online, which track is loaded, whether
the race is running.

Message formats come straight from the game binary:
    Player joined: %d, %s (id: %llu)
    Player left:   %d, %s (id: %llu)
    Loading level: %s, %s (%s)   /  Level loaded: %s, %s (%s)
    Weather changed to %s (%s)
    Car %d (%s) loaded for player %d (%s)
    Race Started / Race Finished / Client Error: %s
"""

from __future__ import annotations

import re
from collections import OrderedDict, deque

# --- wrapper line prefixes -------------------------------------------------

_RE_FULL = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} (\d{2}:\d{2}:\d{2}\.\d+): ?")
_RE_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) +")
_RE_HB = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] heartbeat: game process \d+ alive$")
_RE_ART = re.compile(r"[═║╗╔╝╚▀▄█┌┐└┘─│╗╝╔]")
_RE_SEP = re.compile(r"^-{3,}$")

# First line of a logical message (after prefix stripping).
_RE_START = re.compile(
    r"^(?:Initializing\.\.\.|Version: |Rules changed|Verifying game data checksum\.\.\.|"
    r"Cup config list |Event loop |Loading level: |Level loaded: |Weather changed to |"
    r"Car \d+ |Race Started|Race Finished|Player joined: |Player left: |"
    r"Client Error: |Router port forwarding )"
)

# --- state extraction ------------------------------------------------------

_RE_LEVEL = re.compile(r"^(Loading level|Level loaded): (.+) \(([^()]+)\)$")
_RE_WEATHER = re.compile(r"^Weather changed to (.+?) \(([^()]+)\)$")
_RE_CAR = re.compile(r"^Car (\d+) \(([^)]*)\) loaded for player (\d+) \((.+?)\)$")
_RE_JOIN = re.compile(r"^Player joined: (\d+), (.+?) \(id: (\d+)\)$")
_RE_LEAVE = re.compile(r"^Player left: (\d+), (.+?) \(id: (\d+)\)$")
_RE_VERSION = re.compile(r"^Version: (\S+)")
_RE_LOOP = re.compile(r"^Event loop '(.+?)' loaded")


def _new_state() -> dict:
    return {
        "booted": False,
        "version": "",
        "active_loop": "",
        "track": "",
        "track_id": "",
        "weather": "",
        "phase": "starting",          # starting | racing | intermission
        "races_finished": 0,
        "humans": OrderedDict(),      # slot -> {name, steam_id, car, joined_at}
        "bots": OrderedDict(),        # slot -> {name, car}  (current race only)
        "last_heartbeat": "",
        "client_errors": 0,
    }


def parse_server_log(text: str) -> dict:
    state = _new_state()
    events: deque[dict] = deque(maxlen=20)
    seen: set[tuple[str, str]] = set()

    pending = ""
    pending_ts = ""

    def emit(msg: str, ts: str) -> None:
        nonlocal pending, pending_ts
        if msg.startswith("Initializing..."):
            # New server boot (log file may contain the previous run too):
            # drop old events and the duplicate-detection set.
            events.clear()
            seen.clear()
        key = (ts, msg)
        if key not in seen:
            seen.add(key)
            events.append({"ts": ts, "text": msg})
            _apply(state, msg, ts)
        pending = ""
        pending_ts = ""

    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if _RE_HB.match(line.strip()):
            # Heartbeat: liveness only, keep out of the event feed.
            m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line.strip())
            state["last_heartbeat"] = m.group(1) if m else ""
            continue

        ts = ""
        rest = line
        m = _RE_FULL.match(rest)
        if m:
            ts = f"{m.group(1)} {m.group(2)}"
            rest = rest[m.end():]
        else:
            m = _RE_DATE.match(rest)
            if m:
                ts = m.group(1)
                rest = rest[m.end():]

        if not rest.strip():
            continue
        if _RE_START.match(rest):
            if pending:
                emit(pending, pending_ts)
            pending = rest
            pending_ts = ts
        elif pending:
            pending += rest          # wrapper wrapped a long message mid-word
        elif not _RE_ART.search(rest) and not _RE_SEP.match(rest.strip()) and len(rest.strip()) > 2:
            pending = rest           # unknown-but-real message; may continue
            pending_ts = ts

    if pending:
        emit(pending, pending_ts)

    return _result(state, events)


def _apply(state: dict, msg: str, ts: str) -> None:
    if msg.startswith("Initializing..."):
        # New server boot appended to the same file: drop everything that
        # belongs to the previous run.
        state.clear()
        state.update(_new_state())
        state["booted"] = True
        return

    if m := _RE_VERSION.match(msg):
        state["booted"] = True
        state["version"] = m.group(1)
        return
    if msg == "Verifying game data checksum...":
        state["booted"] = True
        return
    if m := _RE_LOOP.match(msg):
        state["active_loop"] = m.group(1)
        return
    if m := _RE_LEVEL.match(msg):
        state["track"] = m.group(2)
        state["track_id"] = m.group(3)
        state["bots"].clear()        # bot cars are re-loaded after each level
        for h in state["humans"].values():
            h["car"] = ""
        return
    if m := _RE_WEATHER.match(msg):
        state["weather"] = m.group(1)
        return
    if msg == "Race Started":
        state["phase"] = "racing"
        return
    if msg == "Race Finished":
        state["phase"] = "intermission"
        state["races_finished"] += 1
        return
    if m := _RE_JOIN.match(msg):
        slot = int(m.group(1))
        state["humans"][slot] = {
            "slot": slot,
            # The wrapper's clipboard grab already turned non-ASCII name
            # characters into U+FFFD; drop them so the table shows "Burny".
            "name": m.group(2).replace("�", ""),
            "steam_id": m.group(3),
            "car": "",
            "joined_at": ts,
        }
        return
    if m := _RE_LEAVE.match(msg):
        state["humans"].pop(int(m.group(1)), None)
        return
    if m := _RE_CAR.match(msg):
        slot = int(m.group(3))
        name = m.group(4)
        if name.startswith("*BOT"):
            state["bots"][slot] = {"slot": slot, "name": name, "car": m.group(2)}
        elif slot in state["humans"]:
            state["humans"][slot]["car"] = m.group(2)
        return
    if msg.startswith("Client Error:"):
        state["client_errors"] += 1
        return


def _result(state: dict, events: deque[dict]) -> dict:
    return {
        "server": {
            "state": "running" if state["booted"] else "starting",
            "phase": state["phase"],
            "version": state["version"],
            "active_loop": state["active_loop"],
            "races_finished": state["races_finished"],
            "client_errors": state["client_errors"],
            "last_heartbeat": state["last_heartbeat"],
        },
        "race": {
            "track": state["track"],
            "track_id": state["track_id"],
            "weather": state["weather"],
        },
        "humans": list(state["humans"].values()),
        "bots": {
            "count": len(state["bots"]),
            "players": list(state["bots"].values()),
        },
        "events": list(events),
    }
