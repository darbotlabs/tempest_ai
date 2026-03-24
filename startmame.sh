#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUA_SCRIPT="$SCRIPT_DIR/Scripts/main.lua"
DEFAULT_ROMPATH="/home/darbot/mame/roms"

GAME="${TEMPEST_MAME_GAME:-tempest1}"
ROMPATH="${TEMPEST_MAME_ROMPATH:-$DEFAULT_ROMPATH}"
WINDOWED="${TEMPEST_MAME_WINDOWED:-0}"
USE_LUA="${TEMPEST_MAME_USE_LUA:-auto}"

if [[ "${1:-}" == "-kill" ]]; then
    echo "Killing all running MAME instances..."
    pids=$(ps ax | grep "[m]ame.*${GAME}" | awk '{print $1}')
    if [[ -n "$pids" ]]; then
        echo "$pids" | xargs kill -9
        echo "Killed PIDs: $(echo $pids | tr '\n' ' ')"
    else
        echo "No MAME instances found."
    fi
    exit 0
fi

COUNT="${1:-1}"

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [[ "$COUNT" -lt 1 ]]; then
    echo "Usage: $0 [COUNT | -kill]"
    echo "  COUNT   Number of MAME instances to launch (default: 1)"
    echo "  -kill   Kill all running MAME instances"
    exit 1
fi

SOUND_FLAG=""
if [[ "$COUNT" -gt 1 ]]; then
    SOUND_FLAG="-sound none"
fi

VIDEO_ARGS=(-video none)
if [[ "$WINDOWED" == "1" ]]; then
    VIDEO_ARGS=(-window -resolution 640x480)
fi

AUTOBOOT_ARGS=()
if [[ "$USE_LUA" == "1" || ( "$USE_LUA" == "auto" && "$GAME" == "tempest1" ) ]]; then
    AUTOBOOT_ARGS=(-autoboot_script "$LUA_SCRIPT")
fi

echo "Launching $COUNT MAME instance(s)..."
for i in $(seq 1 "$COUNT"); do
    mame "$GAME" "${VIDEO_ARGS[@]}" -nothrottle $SOUND_FLAG -skip_gameinfo "${AUTOBOOT_ARGS[@]}" -rompath "$ROMPATH" &
    echo "  Started instance $i (PID $!)"
done
echo "All instances launched."
