# Wreckfest 2 Docker Server

Run a headless Wreckfest 2 dedicated server in Docker using Wine for seamless Linux compatibility.

Based on the [nvitaterna/wreckfest2-docker-server](https://hub.docker.com/r/nvitaterna/wreckfest2-docker-server) console image, extended with a local build layer that adds Xvfb and gosu so the server runs fully headless with persistent logs and configuration.

## Features

- **Headless operation** — Xvfb provides a virtual display, no GUI required.
- **No game file uploads needed** — SteamCMD downloads the dedicated server (~10 GB) anonymously on first start and checks for updates on every start.
- **Automatic updates** — every container start runs `steamcmd +app_update 3519390 validate`, which applies game updates and repairs missing/corrupted files.
- **Persistent storage** — bind mounts for configs, logs, and game files survive container recreation.
- **Interactive console** — attach to the running server to issue commands.
- **Local image** — builds as `wreckfest2-docker-server:local`, distinct from the upstream image, so Compose can never silently fall back to an outdated pulled image (this previously caused a crash loop with `gosu: command not found` / `Xvfb: command not found`).

## Requirements

- Docker and Docker Compose
- ~4 GB RAM and a multi-core CPU
- Internet access (SteamCMD download/update)
- UDP port 30100 reachable by players

## Quick Start

1. Clone this repo and navigate to it:
   ```bash
   git clone <this-repo> && cd <this-repo>
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

## Troubleshooting

- **Container restarts in a loop / `gosu: command not found` or `Xvfb: command not found`:** the outdated upstream image is being used. Run `docker compose build` then `docker compose up -d --force-recreate`.
- **Empty `docker compose logs` and no game output:** the server process never started — check the crash loop above, then inspect `logs/wine/stderr.log`.
- **Server runs but players can't join:** forward UDP 30100 on your router (UPnP is unavailable inside the container) and check host firewall rules (`ufw allow 30100/udp`).

## Notes

- Game files in `wf2-server/` and runtime logs are gitignored — the repo stays clean for upload/deployment.
- Runtime-generated artifacts (`config/server_cup_config.ccnl`, `config/telemetry/`, `config/~Lock`, `config/save/`) are also gitignored.
- Check the [base image on Docker Hub](https://hub.docker.com/r/nvitaterna/wreckfest2-docker-server) for upstream updates.

Enjoy racing! 🏎️
