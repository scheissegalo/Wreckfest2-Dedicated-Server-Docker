#!/bin/bash
# Hardened entrypoint for headless (VPS) use:
#  - fixes ownership of bind-mounted log/config dirs (Docker creates them as root
#    on a fresh clone; the server runs as steam and cannot write to them)
#  - starts Xvfb on :99 (Wine needs a display even for the dedicated server)
#  - waits for the game window with a timeout instead of hanging forever
set -u

XVFB_DISPLAY="${DISPLAY:-:99}"

# Defaults match the compose environment; overridable for standalone docker run.
XLOGDIR="${XLOGDIR:-/home/steam/logs/x}"
WINELOGDIR="${WINELOGDIR:-/home/steam/logs/wine}"
WFLOGFILEDIR="${WFLOGFILEDIR:-/home/steam/logs/wf}"
STEAMAPPDIR="${STEAMAPPDIR:-/home/steam/wf2-server}"
SERVERCONFIGDIR="${SERVERCONFIGDIR:-/home/steam/wf2-config}"
STEAMAPPID="${STEAMAPPID:-3519390}"
WRAPPERDIR="${WRAPPERDIR:-/home/steam/wrapper}"

echo "----------------"
echo "Preparing environment"
echo "----------------"

# Root phase: bind mounts may be root-owned on a fresh host; make them usable by steam.
mkdir -p "$XLOGDIR" "$WINELOGDIR" "$WFLOGFILEDIR" "$STEAMAPPDIR" "$SERVERCONFIGDIR"
chown -R steam:steam /home/steam/logs
chown steam:steam "$STEAMAPPDIR"
# Recurse so configs written by the (root) config-editor become writable by the
# game again; otherwise it logs "Failed to save server config".
chown -R steam:steam "$SERVERCONFIGDIR"

# Start the virtual display if it is not already reachable.
if ! DISPLAY="$XVFB_DISPLAY" xdotool getdisplaygeometry >/dev/null 2>&1; then
    echo "Starting Xvfb on ${XVFB_DISPLAY}..."
    # A previous container run can leave a stale lock/socket (the filesystem
    # persists across `docker restart`); without cleaning them a fresh Xvfb
    # refuses to start ("Server is already active for display N").
    _dnum="${XVFB_DISPLAY#:}"
    _dnum="${_dnum%%.*}"
    rm -f "/tmp/.X${_dnum}-lock" "/tmp/.X11-unix/X${_dnum}"
    Xvfb "$XVFB_DISPLAY" -screen 0 1024x768x24 >> "$XLOGDIR/stdout.log" 2>> "$XLOGDIR/stderr.log" &
    for _i in $(seq 1 20); do
        DISPLAY="$XVFB_DISPLAY" xdotool getdisplaygeometry >/dev/null 2>&1 && break
        sleep 0.5
    done
fi
export DISPLAY="$XVFB_DISPLAY"

echo "----------------"
echo "Installing Wreckfest 2 Dedicated Server from Steam"
echo "----------------"

gosu steam /usr/games/steamcmd +force_install_dir "$STEAMAPPDIR" +login anonymous \
    +@sSteamCmdForcePlatformType windows +app_update "$STEAMAPPID" validate +quit

echo "----------------"
echo "Finished Installing Wreckfest 2 Dedicated Server from Steam"
echo "----------------"

echo "----------------"
echo "Starting Wreckfest 2 Dedicated Server in WINE"
echo "----------------"

gosu steam bash -c "cd '$STEAMAPPDIR' && exec wine Wreckfest2.exe --server --save-dir='$SERVERCONFIGDIR'" \
    > "$WINELOGDIR/stdout.log" 2> "$WINELOGDIR/stderr.log" &

echo "----------------"
echo "Wreckfest 2 Dedicated Server has been started in WINE"
echo "----------------"

echo "----------------"
echo "Getting Wreckfest Window ID"
echo "----------------"

# Bounded wait: Wine + game start can take a while, but do not hang forever.
WID=""
for _i in $(seq 1 60); do
    WID=$(xdotool search --name Wreckfest 2>/dev/null | head -n1) || true
    [ -n "$WID" ] && break
    sleep 1
done

if [ -n "$WID" ]; then
    sleep 1
    echo "----------------"
    echo "Finished getting Wreckfest Window ID"
    echo "----------------"
    # Place the window top-left; purely cosmetic, never fatal.
    xdotool windowmove "$WID" 0 0 || true
else
    echo "----------------"
    echo "Warning: Wreckfest window not found after 60s;"
    echo "continuing without window placement. Check $WINELOGDIR/stderr.log"
    echo "----------------"
fi

echo "----------------"
echo "Starting Console"
echo "----------------"

sleep 2

exec gosu steam python3 "$WRAPPERDIR/main.py"
