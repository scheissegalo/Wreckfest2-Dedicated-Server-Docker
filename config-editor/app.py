"""Wreckfest 2 dedicated-server config editor.

Small FastAPI service that reads/writes the three JSON config files
(server_config.scnf, *.becl event loops, server_cup_config.ccnl) with
timestamped backups, plus a game-data scan endpoint for GUI dropdowns.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from gamedata import scan_game_data

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
GAME_DIR = Path(os.environ.get("GAME_DIR", "/game"))
BACKUP_DIR = CONFIG_DIR / ".backups"
MAX_BACKUPS = int(os.environ.get("MAX_BACKUPS", "50"))

EDITOR_USER = os.environ.get("EDITOR_USER", "")
EDITOR_PASS = os.environ.get("EDITOR_PASS", "")

ALLOWED_SUFFIXES = {".scnf", ".becl", ".ccnl", ".sprv"}
FILENAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.(scnf|becl|ccnl|sprv)$")

app = FastAPI(title="Wreckfest 2 Config Editor")
security = HTTPBasic(auto_error=False)

STATIC_DIR = Path(__file__).parent / "static"


def _check_auth(creds: HTTPBasicCredentials | None) -> None:
    if not EDITOR_USER and not EDITOR_PASS:
        return  # auth disabled
    if creds is None or creds.username != EDITOR_USER or creds.password != EDITOR_PASS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def auth_dep(creds: HTTPBasicCredentials | None = Depends(security)) -> None:
    _check_auth(creds)


def _safe_path(name: str, must_exist: bool = True) -> Path:
    if not FILENAME_RE.match(name):
        raise HTTPException(status_code=400, detail="Invalid config file name")
    path = CONFIG_DIR / name
    if must_exist and not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return path


def _make_backup(path: Path) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = BACKUP_DIR / f"{path.name}.{ts}.bak"
    # Avoid clobbering within the same second.
    n = 0
    while bak.exists():
        n += 1
        bak = BACKUP_DIR / f"{path.name}.{ts}-{n}.bak"
    shutil.copy2(path, bak)
    # Prune old backups, keep newest MAX_BACKUPS per file.
    baks = sorted(BACKUP_DIR.glob(f"{path.name}.*.bak"))
    for old in baks[: max(0, len(baks) - MAX_BACKUPS)]:
        old.unlink(missing_ok=True)
    return bak


class SavePayload(BaseModel):
    content: dict


@app.get("/api/game-data")
def game_data(_auth: None = Depends(auth_dep)):
    if not GAME_DIR.is_dir():
        raise HTTPException(status_code=409, detail=f"Game dir {GAME_DIR} not mounted")
    return scan_game_data(GAME_DIR)


@app.get("/api/configs")
def list_configs(_auth: None = Depends(auth_dep)):
    out = []
    for p in sorted(CONFIG_DIR.iterdir()):
        if p.is_file() and p.suffix in ALLOWED_SUFFIXES:
            out.append(
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                }
            )
    return out


@app.get("/api/config/{name}")
def get_config(name: str, _auth: None = Depends(auth_dep)):
    path = _safe_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON: {e}")
    return {"name": name, "content": data}


def _write_config(path: Path, content: dict) -> None:
    """Atomically write JSON config, backing up an existing file first.

    This editor runs as root in its own container while the game runs as an
    unprivileged ``steam`` user. If we left files root-owned the game could no
    longer rewrite them ("Failed to save server config"), so after writing we
    hand the file to the config directory's owner (``entry.sh`` chowns that dir
    to ``steam``) and make it group-writable.
    """
    if path.is_file():
        _make_backup(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(content, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    try:
        dir_stat = path.parent.stat()
        os.chown(path, dir_stat.st_uid, dir_stat.st_gid)
        os.chmod(path, 0o664)
    except OSError:
        pass  # best-effort: not fatal if ownership cannot be changed


@app.put("/api/config/{name}")
def put_config(name: str, payload: SavePayload, _auth: None = Depends(auth_dep)):
    # must_exist=False so new event-loop files can be created; validation runs first.
    path = _safe_path(name, must_exist=False)
    err = _validate(name, payload.content)
    if err:
        raise HTTPException(status_code=422, detail=err)
    _write_config(path, payload.content)
    return {"ok": True, "name": name}


@app.get("/api/backups")
def list_backups(_auth: None = Depends(auth_dep)):
    if not BACKUP_DIR.is_dir():
        return []
    out = []
    for p in sorted(BACKUP_DIR.glob("*.*.bak"), reverse=True):
        out.append({"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime})
    return out[:200]


class RestorePayload(BaseModel):
    backup: str


@app.post("/api/restore")
def restore_backup(payload: RestorePayload, _auth: None = Depends(auth_dep)):
    if "/" in payload.backup or ".." in payload.backup:
        raise HTTPException(status_code=400, detail="Invalid backup name")
    src = BACKUP_DIR / payload.backup
    if not src.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    # backup name is <config>.<ts>[ -n].bak -> config file is everything before
    # the timestamp; recover via suffix match against known configs.
    target_name = None
    for p in CONFIG_DIR.iterdir():
        if p.is_file() and payload.backup.startswith(p.name + "."):
            target_name = p.name
            break
    if target_name is None:
        # Config may have been deleted; derive from name pattern.
        m = re.match(r"^(.+\.(?:scnf|becl|ccnl))\.\d{8}-\d{6}", payload.backup)
        if not m:
            raise HTTPException(status_code=400, detail="Cannot map backup to config")
        target_name = m.group(1)
    target = CONFIG_DIR / target_name
    if target.is_file():
        _make_backup(target)
    shutil.copy2(src, target)
    return {"ok": True, "restored": target_name}


def _validate(name: str, content: dict) -> str | None:
    if not isinstance(content, dict):
        return "Root must be a JSON object"
    if name.endswith(".scnf"):
        for key in ("net server config", "game server config"):
            v = content.get(key)
            if not isinstance(v, list) or not v or not isinstance(v[0], dict):
                return f"'{key}' must be a non-empty array of objects"
        net = content["net server config"][0]
        if not isinstance(net.get("name"), str):
            return "net server config[0].name must be a string"
        game = content["game server config"][0]
        if "event loop name" in game and not isinstance(game["event loop name"], str):
            return "event loop name must be a string"
        return None
    if name.endswith(".becl"):
        events = content.get("events")
        if not isinstance(events, list):
            return "'events' must be an array"
        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                return f"events[{i}] must be an object"
            level = ev.get("level")
            rules = ev.get("rules")
            if not isinstance(level, list) or not level or not isinstance(level[0], dict):
                return f"events[{i}].level must be a non-empty array"
            lid = level[0].get("level id")
            if not isinstance(lid, str) or not lid:
                return f"events[{i}].level[0].level id must be a non-empty string"
            if not isinstance(rules, list) or not rules or not isinstance(rules[0], dict):
                return f"events[{i}].rules must be a non-empty array"
            bot = ev.get("bot count", 0)
            if not isinstance(bot, int) or not 0 <= bot <= 24:
                return f"events[{i}].bot count must be an integer 0-24"
        return None
    if name.endswith(".ccnl"):
        cups = content.get("cups")
        if not isinstance(cups, list):
            return "'cups' must be an array"
        for i, cup in enumerate(cups):
            if not isinstance(cup, dict):
                return f"cups[{i}] must be an object"
            if not isinstance(cup.get("cup name"), str):
                return f"cups[{i}].cup name must be a string"
            el = cup.get("event loop")
            if not isinstance(el, str):
                return f"cups[{i}].event loop must be a string"
        return None
    if name.endswith(".sprv"):
        roles = content.get("roles", [])
        if not isinstance(roles, list):
            return "'roles' must be an array"
        for i, role in enumerate(roles):
            if not isinstance(role, dict):
                return f"roles[{i}] must be an object"
            pid = role.get("platform id")
            if isinstance(pid, bool) or not isinstance(pid, (int, str)):
                return f"roles[{i}].platform id must be a SteamID64 string or integer"
            if not isinstance(role.get("role"), str) or not role["role"]:
                return f"roles[{i}].role must be a non-empty string"
        bans = content.get("bans", [])
        if not isinstance(bans, list):
            return "'bans' must be an array"
        return None
    return None


class GenerateLoopPayload(BaseModel):
    name: str
    # "intrinsic" -> one event per level using the level's own default mode;
    # otherwise one event per (level, mode) for each listed mode id.
    modes: list[str] = ["intrinsic"]
    level_ids: list[str] | None = None  # None/empty -> every level with an event
    weather: str = ""
    ai_set: str = "career/ai-class-all.aist"
    laps: int = 5
    time_limit: int = 3
    teams: int = 1
    max_participants: int = 24
    bot_count: int = 8
    reset_delay: int = 2
    damage: str = ""
    flags: str = ""


def _make_event(level_id: str, mode: str, p: GenerateLoopPayload) -> dict:
    return {
        "level": [
            {
                "level id": level_id,
                "weather path": p.weather,
                "ai set path": p.ai_set,
                "game mode id": mode,
            }
        ],
        "rules": [
            {
                "laps": p.laps,
                "time limit": p.time_limit,
                "number of teams": p.teams,
                "max number of participants": p.max_participants,
                "flags": p.flags,
                "car reset delay (seconds)": p.reset_delay,
                "vehicle damage id": p.damage,
            }
        ],
        "bot count": p.bot_count,
    }


@app.post("/api/generate-loop")
def generate_loop(payload: GenerateLoopPayload, _auth: None = Depends(auth_dep)):
    name = payload.name.strip()
    if not name.endswith(".becl"):
        name += ".becl"
    path = _safe_path(name, must_exist=False)

    game = scan_game_data(GAME_DIR)
    tracks = {t["id"]: t for t in game["tracks"]}
    wanted = payload.level_ids or [
        t["id"] for t in game["tracks"] if t.get("has_event")
    ]
    unknown = sorted({lid for lid in wanted if lid not in tracks})
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown level id(s): {', '.join(unknown)}")

    modes = [m.strip() for m in payload.modes if m.strip()]
    if not modes:
        modes = ["intrinsic"]

    events: list[dict] = []
    for lid in wanted:
        if "intrinsic" in modes:
            events.append(_make_event(lid, tracks[lid].get("default_mode", ""), payload))
        else:
            for mode in modes:
                events.append(_make_event(lid, mode, payload))

    content = {"bbmeta": "becl v0 n1", "events": events}
    err = _validate(name, content)
    if err:
        raise HTTPException(status_code=422, detail=err)
    _write_config(path, content)
    return {"ok": True, "name": name, "events": len(events)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/static/{path:path}")
def static(path: str):
    f = (STATIC_DIR / path).resolve()
    if not str(f).startswith(str(STATIC_DIR.resolve())) or not f.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(f)


@app.exception_handler(HTTPException)
async def http_exc(_req: Request, exc: HTTPException):
    # Preserve headers (notably WWW-Authenticate for Basic auth) so the
    # browser shows its native login popup instead of raw JSON.
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )
