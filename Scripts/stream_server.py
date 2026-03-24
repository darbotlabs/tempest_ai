#!/usr/bin/env python3
"""Managed live viewport server for tempest_ai."""

import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request

try:
    from config import (
        DEFAULT_VIEWPORT_GAME,
        SETTINGS_PATH,
        VIEWPORT_GAME_OPTIONS,
        game_settings,
        normalize_viewport_game,
    )
except ImportError:
    from Scripts.config import (
        DEFAULT_VIEWPORT_GAME,
        SETTINGS_PATH,
        VIEWPORT_GAME_OPTIONS,
        game_settings,
        normalize_viewport_game,
    )


BOUNDARY = b"--frame"
PORT = int(os.getenv("TEMPEST_VIEWPORT_PORT", "8766"))
DISPLAY = os.getenv("TEMPEST_VIEWPORT_DISPLAY", ":99")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DASHBOARD_PORT = int(os.getenv("TEMPEST_DASHBOARD_PORT", "8765"))
DASHBOARD_ROOT = f"http://127.0.0.1:{DASHBOARD_PORT}"
PUBLIC_HOST = os.getenv("TEMPEST_DASHBOARD_PUBLIC_HOST", "").strip()
MAME_BIN = os.getenv("TEMPEST_MAME_BIN", "/usr/games/mame")
ROMPATH = os.getenv("TEMPEST_VIEWPORT_ROMPATH", os.path.join(PROJECT_ROOT, "MAME_ROMS"))
LUA_SCRIPT = os.path.join(SCRIPT_DIR, "main.lua")
MAME_LOG = os.getenv("TEMPEST_VIEWPORT_MAME_LOG", "/tmp/mame_vis.log")
SETTINGS_FILE = SETTINGS_PATH if os.path.isabs(SETTINGS_PATH) else os.path.join(PROJECT_ROOT, SETTINGS_PATH)
SUPPORTED_GAMES = {
    game_id: {
        "label": label,
        "use_lua": game_id == "tempest1",
    }
    for game_id, label in VIEWPORT_GAME_OPTIONS
}

clients = []
clients_lock = threading.Lock()
latest_frame = b""
frame_lock = threading.Lock()
settings_lock = threading.Lock()


def load_selected_game() -> str:
    with settings_lock:
        game_settings.load(SETTINGS_FILE)
        return normalize_viewport_game(getattr(game_settings, "selected_game", DEFAULT_VIEWPORT_GAME))


def save_selected_game(game: object) -> str:
    game_id = normalize_viewport_game(game)
    with settings_lock:
        game_settings.load(SETTINGS_FILE)
        game_settings.selected_game = game_id
        game_settings.save(SETTINGS_FILE)
    return game_id


def dashboard_url() -> str:
    host = PUBLIC_HOST or socket.gethostname() or "127.0.0.1"
    return f"http://{host}:{DASHBOARD_PORT}/?admin=yes"


def render_watch_html() -> bytes:
    dashboard_href = dashboard_url()
    tiles = "\n".join(
        (
            f'      <button class="game-tile{" active" if game_id == DEFAULT_VIEWPORT_GAME else ""}" '
            f'data-game="{game_id}"><span class="lbl">Game Tile</span>'
            f'<span class="val">{meta["label"]}</span>'
            f'<span class="sub">{"AI-controlled live viewport" if meta["use_lua"] else "Launch from MAME_ROMS"}</span>'
            f"</button>"
        )
        for game_id, meta in SUPPORTED_GAMES.items()
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arcade AI — Live</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#050510;color:#0ff;font-family:'Courier New',monospace;min-height:100vh;display:flex;flex-direction:column}}
.layout{{display:flex;flex:1;align-items:stretch}}
.panel{{width:220px;flex-shrink:0;display:flex;flex-direction:column;gap:7px;padding:10px;background:rgba(0,0,0,.55);border:1px solid rgba(0,255,255,.12)}}
.panel.left{{border-right:none}}.panel.right{{border-left:none}}
.game-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:6px;background:#000}}
.game-wrap img{{width:100%;max-height:82vh;object-fit:contain;image-rendering:pixelated;border:1px solid rgba(0,255,255,.2);box-shadow:0 0 40px rgba(0,255,255,.08)}}
.card{{background:rgba(0,20,40,.75);border:1px solid rgba(0,255,255,.16);border-radius:4px;padding:7px 9px}}
.card .lbl{{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(0,255,255,.6);margin-bottom:3px}}
.card .val{{font-size:22px;color:#0ff;text-shadow:0 0 10px rgba(0,255,255,.5);line-height:1.1}}
.card .sub{{font-size:10px;color:rgba(0,255,255,.5);margin-top:2px}}
.tile-grid{{display:grid;grid-template-columns:1fr;gap:7px}}
.game-tile{{width:100%;text-align:left;background:rgba(0,20,40,.82);border:1px solid rgba(0,255,255,.18);border-radius:4px;padding:9px;cursor:pointer;color:inherit;font-family:inherit;transition:border-color .15s, box-shadow .15s}}
.game-tile:hover{{border-color:rgba(0,255,255,.45);box-shadow:0 0 12px rgba(0,255,255,.15)}}
.game-tile.active{{border-color:rgba(57,255,20,.75);box-shadow:0 0 18px rgba(57,255,20,.18), inset 0 0 14px rgba(57,255,20,.10)}}
.game-tile:disabled{{opacity:.65;cursor:wait}}
.game-tile .lbl{{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(0,255,255,.6);margin-bottom:3px;display:block}}
.game-tile .val{{font-size:20px;color:#f3fbff;text-shadow:0 0 10px rgba(0,255,255,.4);line-height:1.1;display:block}}
.game-tile .sub{{font-size:10px;color:rgba(0,255,255,.5);margin-top:3px;display:block}}
header{{display:flex;align-items:center;justify-content:space-between;padding:6px 14px;background:rgba(0,0,0,.85);border-bottom:1px solid rgba(0,255,255,.12)}}
header h1{{font-size:12px;letter-spacing:3px;text-transform:uppercase}}
header a{{color:#555;font-size:11px;text-decoration:none}}header a:hover{{color:#0ff}}
.status{{display:flex;align-items:center;gap:6px;font-size:11px}}
.dot{{width:7px;height:7px;border-radius:50%;background:#0f0;box-shadow:0 0 6px #0f0;transition:background .3s}}
.audio-bar{{display:flex;align-items:center;gap:10px;padding:5px 14px;background:rgba(0,0,0,.85);border-top:1px solid rgba(0,255,255,.1);font-size:11px;color:rgba(0,255,255,.7)}}
#trackName{{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ab{{background:none;border:1px solid rgba(0,255,255,.3);color:#0ff;border-radius:999px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:inherit}}
.ab:hover{{border-color:#0ff;box-shadow:0 0 8px rgba(0,255,255,.25)}}
#gameSwitchStatus{{min-height:1.2em}}
@media(max-width:860px){{
  .layout{{flex-direction:column}}
  .panel{{width:100%;flex-direction:row;flex-wrap:wrap;gap:6px;border:none;border-bottom:1px solid rgba(0,255,255,.1)}}
  .panel.right{{border-bottom:none;border-top:1px solid rgba(0,255,255,.1)}}
  .panel .card,.panel .game-tile{{flex:1;min-width:120px}}
  .tile-grid{{grid-template-columns:repeat(2,minmax(120px,1fr));width:100%}}
  .game-wrap img{{max-height:55vw}}
}}
</style>
</head>
<body>
<header>
  <h1>&#9654; <span id="liveTitleGame">Arcade</span> AI &mdash; Live</h1>
  <div class="status"><span class="dot" id="dot"></span><span id="stxt">Connecting...</span></div>
  <a href="{dashboard_href}">&#8592; Dashboard</a>
</header>
<div class="layout">
  <div class="panel left">
    <div class="card"><div class="lbl">Current Viewport Game</div><div class="val" id="currentGame">Arcade</div><div class="sub" id="gameSwitchStatus">Using local MAME_ROMS</div></div>
    <div class="tile-grid">
{tiles}
    </div>
    <div class="card"><div class="lbl">FPS</div><div class="val" id="fps">-</div></div>
    <div class="card"><div class="lbl">Avg Level</div><div class="val" id="level">-</div><div class="sub" id="peakLvl"></div></div>
    <div class="card"><div class="lbl">Clients</div><div class="val" id="clnts">-</div></div>
    <div class="card"><div class="lbl">Reward 1M</div><div class="val" id="rew">-</div></div>
    <div class="card"><div class="lbl">High Score</div><div class="val" id="hi">-</div></div>
  </div>
  <div class="game-wrap"><img src="/stream" alt="Live game" /></div>
  <div class="panel right">
    <div class="card"><div class="lbl">Loss</div><div class="val" id="loss">-</div></div>
    <div class="card"><div class="lbl">Grad Norm</div><div class="val" id="gnorm">-</div></div>
    <div class="card"><div class="lbl">Inference</div><div class="val" id="inf">-</div><div class="sub">ms avg</div></div>
    <div class="card"><div class="lbl">Buffer</div><div class="val" id="buf">-</div></div>
    <div class="card"><div class="lbl">Agreement</div><div class="val" id="agr">-</div></div>
  </div>
</div>
<div class="audio-bar">
  <button class="ab" id="playBtn" onclick="toggleAudio()">&#9654; Audio</button>
  <span id="trackName">Loading playlist...</span>
  <button class="ab" onclick="nextTrack()">&#9658;&#9658;</button>
</div>
<audio id="bgAudio" preload="auto"></audio>
<script>
const METRICS='/api/now';
const PLAYLIST='/api/audio_playlist';
const GAME_SETTINGS='/api/game_settings';
const SELECT_GAME='/api/select_game';
const GAME_LABELS={json.dumps({game_id: meta["label"] for game_id, meta in SUPPORTED_GAMES.items()})};
let tracks=[],idx=0,enabled=false,currentGame={json.dumps(DEFAULT_VIEWPORT_GAME)};
const audio=document.getElementById('bgAudio');
const statusEl=document.getElementById('gameSwitchStatus');
const currentGameEl=document.getElementById('currentGame');
const titleGameEl=document.getElementById('liveTitleGame');
const tileEls=[...document.querySelectorAll('.game-tile')];
async function loadPL(){{try{{const r=await fetch(PLAYLIST);const d=await r.json();tracks=d.tracks||[];if(tracks.length)setTrack(0);}}catch(e){{}}}}
function setTrack(i){{if(!tracks.length)return;idx=(i+tracks.length)%tracks.length;audio.src=tracks[idx].url;document.getElementById('trackName').textContent=tracks[idx].name;if(enabled)audio.play().catch(()=>{{}});}}
function toggleAudio(){{enabled=!enabled;document.getElementById('playBtn').textContent=enabled?'\\u23f8 Audio':'\\u25b6 Audio';if(enabled)audio.play().catch(()=>{{}});else audio.pause();}}
function nextTrack(){{setTrack(idx+1);}}
audio.addEventListener('ended',()=>setTrack(idx+1));
function fmt(v,d=0){{if(v===null||v===undefined)return'-';const n=Number(v);if(isNaN(n))return'-';if(Math.abs(n)>=1e6)return(n/1e6).toFixed(1)+'M';if(Math.abs(n)>=1e3)return(n/1e3).toFixed(1)+'K';return n.toFixed(d);}}
function syncSelectedGame(game){{currentGame=GAME_LABELS[game]?game:{json.dumps(DEFAULT_VIEWPORT_GAME)};const label=GAME_LABELS[currentGame];currentGameEl.textContent=label;titleGameEl.textContent=label;document.title=label+' AI — Live';tileEls.forEach(el=>el.classList.toggle('active',el.dataset.game===currentGame));}}
async function refreshGameSettings(){{try{{const r=await fetch(GAME_SETTINGS+'?t='+Date.now(),{{cache:'no-store'}});const d=await r.json();if(d.selected_game)syncSelectedGame(d.selected_game);}}catch(e){{}}}}
async function selectGame(game){{
  tileEls.forEach(el=>el.disabled=true);
  statusEl.textContent='Switching viewport to '+(GAME_LABELS[game]||game)+'...';
  try{{
    const r=await fetch(SELECT_GAME,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{selected_game:game}})}});
    const d=await r.json();
    syncSelectedGame(d.selected_game||game);
    statusEl.textContent=d.message||('Viewport loaded '+(GAME_LABELS[d.selected_game||game]||game));
  }}catch(e){{
    statusEl.textContent='Viewport switch failed';
  }}finally{{
    tileEls.forEach(el=>el.disabled=false);
  }}
}}
tileEls.forEach(el=>el.addEventListener('click',()=>selectGame(el.dataset.game)));
async function poll(){{try{{const r=await fetch(METRICS+'?t='+Date.now(),{{cache:'no-store'}});const d=await r.json();
if(d.game_settings&&d.game_settings.selected_game)syncSelectedGame(d.game_settings.selected_game);
document.getElementById('fps').textContent=fmt(d.fps);
document.getElementById('level').textContent=fmt(d.average_level,1);
document.getElementById('peakLvl').textContent='Peak: Lvl '+fmt(d.peak_level);
document.getElementById('clnts').textContent=d.client_count ?? '-';
document.getElementById('rew').textContent=fmt(d.dqn_1m);
document.getElementById('hi').textContent=fmt(d.peak_game_score);
document.getElementById('loss').textContent=fmt(d.loss,3);
document.getElementById('gnorm').textContent=fmt(d.grad_norm,3);
document.getElementById('inf').textContent=fmt(d.avg_inf_ms,1);
document.getElementById('buf').textContent=fmt(d.memory_buffer_size);
document.getElementById('agr').textContent=fmt((d.agreement_1m||0)*100,1)+'%';
document.getElementById('dot').style.background='#0f0';document.getElementById('stxt').textContent='Live';
}}catch(e){{document.getElementById('dot').style.background='#f00';document.getElementById('stxt').textContent='Offline';}}}}
loadPL();refreshGameSettings();poll();setInterval(poll,1500);
</script>
</body>
</html>"""
    return html.encode("utf-8")


WATCH_HTML = render_watch_html()


def send_response(conn, status, body, content_type=b"text/plain; charset=utf-8"):
    reasons = {
        200: b"OK",
        400: b"Bad Request",
        404: b"Not Found",
        405: b"Method Not Allowed",
        502: b"Bad Gateway",
    }
    headers = [
        b"HTTP/1.1 " + str(status).encode() + b" " + reasons.get(status, b"OK"),
        b"Content-Type: " + content_type,
        b"Content-Length: " + str(len(body)).encode(),
        b"Access-Control-Allow-Origin: *",
    ]
    conn.sendall(b"\r\n".join(headers) + b"\r\n\r\n" + body)


def read_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    if not data:
        return None
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    parts = lines[0].decode("utf-8", "ignore").split(" ")
    method = parts[0] if parts else "GET"
    target = parts[1] if len(parts) > 1 else "/"
    headers = {}
    for raw in lines[1:]:
        if b":" not in raw:
            continue
        key, value = raw.split(b":", 1)
        headers[key.strip().lower().decode("utf-8", "ignore")] = value.strip().decode("utf-8", "ignore")
    content_length = int(headers.get("content-length", "0") or "0")
    while len(body) < content_length:
        chunk = conn.recv(min(4096, content_length - len(body)))
        if not chunk:
            break
        body += chunk
    path = target.split("?", 1)[0]
    return method, path, body


def proxy_get(path):
    with urllib.request.urlopen(DASHBOARD_ROOT + path, timeout=2) as response:
        body = response.read()
        ct = response.headers.get_content_type() or "application/json"
        if path in {"/api/now", "/api/game_settings"}:
            body = inject_selected_game(path, body)
        return body, ct.encode()


def proxy_post_settings(payload):
    req = urllib.request.Request(
        DASHBOARD_ROOT + "/api/game_settings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as response:
        return response.read()


def inject_selected_game(path, body):
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return body
    selected_game = load_selected_game()
    if path == "/api/now":
        if not isinstance(payload, dict):
            payload = {}
        gs = payload.get("game_settings")
        if not isinstance(gs, dict):
            gs = {}
            payload["game_settings"] = gs
        gs["selected_game"] = selected_game
    elif path == "/api/game_settings":
        if not isinstance(payload, dict):
            payload = {}
        payload["selected_game"] = selected_game
    return json.dumps(payload).encode("utf-8")


def iter_visible_mame_pids():
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmdline = fh.read().replace(b"\x00", b" ").decode("utf-8", "ignore")
            with open(f"/proc/{pid}/environ", "rb") as fh:
                environ = fh.read()
        except OSError:
            continue
        if "mame" not in cmdline or "-window" not in cmdline:
            continue
        if f"DISPLAY={DISPLAY}".encode() not in environ:
            continue
        yield pid


def stop_visible_mame():
    pids = list(iter_visible_mame_pids())
    if not pids:
        return []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 3.0
    alive = set(pids)
    while alive and time.time() < deadline:
        time.sleep(0.1)
        alive = {pid for pid in alive if os.path.exists(f"/proc/{pid}")}
    for pid in list(alive):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return pids


def launch_viewport_game(game):
    game_id = normalize_viewport_game(game)
    stop_visible_mame()
    cmd = [
        MAME_BIN,
        game_id,
        "-nothrottle",
        "-sound",
        "none",
        "-skip_gameinfo",
        "-window",
        "-resolution",
        "640x480",
        "-rompath",
        ROMPATH,
    ]
    if SUPPORTED_GAMES[game_id]["use_lua"]:
        cmd.extend(["-autoboot_script", LUA_SCRIPT])
    env = os.environ.copy()
    env["DISPLAY"] = DISPLAY
    os.makedirs(os.path.dirname(MAME_LOG) or ".", exist_ok=True)
    with open(MAME_LOG, "ab") as logfh:
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=logfh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def ensure_viewport_game_running():
    if list(iter_visible_mame_pids()):
        return
    launch_viewport_game(load_selected_game())


def capture_loop():
    global latest_frame
    while True:
        try:
            proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-f",
                    "x11grab",
                    "-r",
                    "24",
                    "-s",
                    "640x480",
                    "-i",
                    DISPLAY,
                    "-vf",
                    "scale=640:480",
                    "-f",
                    "mpjpeg",
                    "-q:v",
                    "4",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            buf = b""
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    start = buf.find(b"\xff\xd8")
                    end = buf.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start >= 0 and end >= 0:
                        frame = buf[start : end + 2]
                        with frame_lock:
                            latest_frame = frame
                        with clients_lock:
                            dead = []
                            for client in clients:
                                try:
                                    client.sendall(
                                        BOUNDARY
                                        + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                        + str(len(frame)).encode()
                                        + b"\r\n\r\n"
                                        + frame
                                        + b"\r\n"
                                    )
                                except Exception:
                                    dead.append(client)
                            for dead_client in dead:
                                clients.remove(dead_client)
                        buf = buf[end + 2 :]
                    else:
                        break
        except Exception:
            time.sleep(1)


def handle_select_game(conn, body):
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        send_response(conn, 400, b'{"error":"bad request"}', b"application/json")
        return
    game_id = save_selected_game(payload.get("selected_game"))
    try:
        proxy_post_settings({"selected_game": game_id})
    except Exception:
        pass
    pid = launch_viewport_game(game_id)
    response = {
        "selected_game": game_id,
        "message": f"Viewport switched to {SUPPORTED_GAMES[game_id]['label']} (PID {pid})",
    }
    send_response(conn, 200, json.dumps(response).encode("utf-8"), b"application/json")


def handle_client(conn):
    try:
        request = read_request(conn)
        if not request:
            conn.close()
            return
        method, path, body = request
        if path == "/stream":
            conn.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n"
                b"Cache-Control: no-cache\r\nConnection: keep-alive\r\nAccess-Control-Allow-Origin: *\r\n\r\n"
            )
            with clients_lock:
                clients.append(conn)
            return
        if path == "/snapshot":
            with frame_lock:
                frame = latest_frame or b""
            send_response(conn, 200, frame, b"image/jpeg")
            conn.close()
            return
        if path == "/api/select_game":
            if method != "POST":
                send_response(conn, 405, b'{"error":"method not allowed"}', b"application/json")
            else:
                handle_select_game(conn, body)
            conn.close()
            return
        if path.startswith("/api/"):
            if method != "GET":
                send_response(conn, 405, b'{"error":"method not allowed"}', b"application/json")
            else:
                try:
                    proxy_body, ct = proxy_get(path)
                    send_response(conn, 200, proxy_body, ct)
                except Exception as exc:
                    if path == "/api/game_settings":
                        fallback = json.dumps({"selected_game": load_selected_game()}).encode("utf-8")
                        send_response(conn, 200, fallback, b"application/json")
                    elif path == "/api/now":
                        fallback = json.dumps({"game_settings": {"selected_game": load_selected_game()}}).encode("utf-8")
                        send_response(conn, 200, fallback, b"application/json")
                    else:
                        send_response(conn, 502, str(exc).encode("utf-8"))
            conn.close()
            return
        send_response(conn, 200, WATCH_HTML, b"text/html; charset=utf-8")
        conn.close()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def serve():
    ensure_viewport_game_running()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PORT))
    server.listen(32)
    print(f"Stream server on :{PORT}", flush=True)
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle_client, args=(conn,), daemon=True).start()


threading.Thread(target=capture_loop, daemon=True).start()
serve()
