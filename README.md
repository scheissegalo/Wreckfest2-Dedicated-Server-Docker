# Wreckfest 2 Docker Server

Run a headless Wreckfest 2 dedicated server in Docker using Wine for seamless Linux compatibility.

Based on the [nvitaterna/wreckfest2-docker-server](https://hub.docker.com/r/nvitaterna/wreckfest2-docker-server) console image, extended with a local build layer that adds Xvfb and gosu so the server runs fully headless with persistent logs and configuration.

## Features

- **Headless operation** — Xvfb provides a virtual display, no GUI required.
- **No game file uploads needed** — SteamCMD downloads the dedicated server (~10 GB) anonymously on first start and checks for updates on every start.
- **Automatic updates** — every container start runs `steamcmd +app_update 3519390 validate`, which applies game updates and repairs missing/corrupted files.
- **Persistent storage** — bind mounts for configs, logs, and game files survive container recreation.
- **Interactive console** — attach to the running server to issue commands.
- **Web config editor** — bundled GUI (`config-editor/` service) for editing `server_config.scnf`, event loops, and cup configs with dropdowns for all tracks, weathers, AI sets, and game modes (details below).
- **Local image** — builds as `wreckfest2-docker-server:local`, distinct from the upstream image, so Compose can never silently fall back to an outdated pulled image (this previously caused a crash loop with `gosu: command not found` / `Xvfb: command not found`).

## Requirements

- Docker and Docker Compose
- ~4 GB RAM and a multi-core CPU
- Internet access (SteamCMD download/update)
- UDP port 30100 reachable by players

## Quick Start

1. Clone this repo and navigate to it:
   ```bash
   git clone https://github.com/scheissegalo/Wreckfest2-Dedicated-Server-Docker && cd Wreckfest2-Dedicated-Server-Docker
   ```
2. Create the host directories (game files are **not** needed — SteamCMD fetches them):
   ```bash
   mkdir -p config logs wf2-server
   ```
3. Put your server config files in `./config`:
   - `server_config.scnf`
   - `event_loop.becl`
   - `default_loop.becl`
4. Build and start:
   ```bash
   docker compose up -d --build
   ```
   `--build` is required on first start so the local image (with Xvfb/gosu) is built. `docker-compose.yml` and `Dockerfile` must be in the same directory.
5. Watch the first boot download the game and start the server:
   ```bash
   docker compose logs -f
   ```
   The initial download is several GB and takes a while. Later boots validate and update quickly, then launch the server.
6. Connect clients to your host's IP on **UDP 30100** (the server also appears in the in-game server list).
7. If using UFW (recommended):
   ```bash
   ufw allow 30100/udp
   ```

## Updating

- **Game updates:** automatic — SteamCMD runs on every container start.
- **Image/Dockerfile changes:** run `docker compose up -d --build` again.
- **Server config changes:** edit files in `./config`, then `docker compose restart wreckfest-server`.

## Interactive Console

```bash
docker compose attach wreckfest-server
```

Type `help` for available commands.

Use **CTRL-C** to detach from the console. Only use `exit`/`quit` if you actually want to stop the server.

## Logs

| File | Content |
|---|---|
| `docker compose logs -f` | Full startup console (SteamCMD, Wine, game server output) |
| `logs/wf/server.log` | Game server log (may stay empty while running; live output is in `docker compose logs`) |
| `logs/wine/stdout.log`, `logs/wine/stderr.log` | Wine output |
| `logs/x/stdout.log`, `logs/x/stderr.log` | Xvfb output |

Log files are gitignored; empty `.gitkeep` placeholders keep the directories in a fresh clone.

## Web Config Editor

A small web GUI ships in this repo (`config-editor/` service) for editing the three config files without hand-editing JSON. It runs alongside the game server and is bound to **localhost only** by default.

```bash
docker compose up -d --build config-editor
# then open http://127.0.0.1:8085
```

### What it does

- **Server tab** — edit server name, description, password, port, countdown/voting times, server flags, ban durations, and pick which `.becl` event loop is active (no more guessing whether `default_loop` or `event_loop` is loaded — the Event Loop tab also badges the active file).
- **Event Loop tab** — edit any `.becl` file: add/remove/duplicate/reorder (drag) events; per-event dropdowns for **track** (pretty names like "Speedway – Inner Oval", extracted from the game files, with ID fallback), **weather** (filtered to the selected track's venue, pretty names), **AI set** (virtual class sets + on-disk sets like "American Cars"), and **game mode** (banger race, derby, deathmatch, folk race, suicide race, waypoint race). Rules fields (laps, time limit, participants, bots, damage, reset delay, race flags) are validated.
- **Cups tab** — edit `server_cup_config.ccnl`: cups players vote between in the lobby, including scoring, start order, car restrictions, and which event loop each cup runs.
- **Backups tab** — every save creates a timestamped backup under `config/.backups/` (last 50 kept per file); restore from the tab with one click.
- **Raw JSON tab** — escape hatch to edit any config file as text with server-side validation.

Track, weather, and AI metadata is **scanned from the mounted game files at runtime** (`./wf2-server` is mounted read-only), so dropdowns stay current after game updates automatically.

### Securing it

By default the editor listens on `127.0.0.1:8085` only (not reachable from the network). To expose it, set environment variables (e.g. in a `.env` file next to `docker-compose.yml`):

```bash
EDITOR_BIND=0.0.0.0    # listen on all interfaces
EDITOR_USER=admin      # HTTP basic auth username
EDITOR_PASS=changeme   # HTTP basic auth password
MAX_BACKUPS=100        # optional, default 50
```

**Always set `EDITOR_USER`/`EDITOR_PASS` if you change `EDITOR_BIND` away from localhost** — the editor can change your server password and configs.

### Notes

- Config changes only take effect after a server restart: `docker compose restart wreckfest-server`.
- The editor validates structure before saving (required fields, ranges like bots 0–24, laps 1–500) and refuses invalid JSON — it won't corrupt your configs.
- The game occasionally rewrites `server_config.scnf`/`server_cup_config.ccnl` at runtime; use the editor's Reload (Raw tab) or reload the page before editing to pick up game-side changes.

## Troubleshooting

- **Container restarts in a loop / `gosu: command not found` or `Xvfb: command not found`:** the outdated upstream image is being used. Run `docker compose build` then `docker compose up -d --force-recreate`.
- **Empty `docker compose logs` and no game output:** the server process never started — check the crash loop above, then inspect `logs/wine/stderr.log`.
- **`Permission denied` writing to `/home/steam/logs/...` on a fresh VPS/clone:** Docker creates the bind-mounted `./logs` (and `./config`) directories as root; the hardened `entry.sh` fixes ownership automatically at startup, but if you see this error you're running an old image — rebuild with `docker compose up -d --build --force-recreate`.
- **`Error: Can't open display` / `Failed creating new xdo instance` in a loop:** the virtual display (Xvfb) isn't running or the container predates the hardened entrypoint. Rebuild as above; `entry.sh` now starts Xvfb itself and only waits up to 60s for the game window instead of hanging forever.
- **`Warning: Wreckfest window not found after 60s`:** Wine failed to start the game — check `logs/wine/stderr.log`. The server keeps going (console still starts) so the warning won't mask other issues.
- **Server runs but players can't join:** forward UDP 30100 on your router (UPnP is unavailable inside the container) and check host firewall rules (`ufw allow 30100/udp`).

## Notes

- Game files in `wf2-server/` and runtime logs are gitignored — the repo stays clean for upload/deployment.
- Runtime-generated artifacts (`config/server_cup_config.ccnl`, `config/telemetry/`, `config/~Lock`, `config/save/`, `config/.backups/`) are also gitignored.
- Check the [base image on Docker Hub](https://hub.docker.com/r/nvitaterna/wreckfest2-docker-server) for upstream updates.

Enjoy racing! 🏎️
