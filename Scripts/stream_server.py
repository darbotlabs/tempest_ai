#!/usr/bin/env python3
"""Managed live viewport server for tempest_ai."""

import json
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request

try:
    from config import (
        DEFAULT_VIEWPORT_GAME,
        SETTINGS_PATH,
        game_settings,
        normalize_viewport_game,
    )
except ImportError:
    from Scripts.config import (
        DEFAULT_VIEWPORT_GAME,
        SETTINGS_PATH,
        game_settings,
        normalize_viewport_game,
    )

try:
    from game_catalog import get_catalog
except ImportError:
    from Scripts.game_catalog import get_catalog


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
MAME_FRONTEND = os.path.join(PROJECT_ROOT, "MAME_FRONTEND", "MAME")

_LUA_GAMES = frozenset(("tempest1", "tempest", "tempest1r", "tempest2", "tempest3"))


def _game_uses_lua(game_id: str) -> bool:
    return game_id in _LUA_GAMES

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
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Arcade AI — Live</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#050510;color:#0ff;font-family:'Courier New',monospace;min-height:100vh;display:flex;flex-direction:column}}
.layout{{display:flex;flex:1;align-items:stretch;overflow:hidden}}

/* --- Left library panel --- */
.panel.left{{width:260px;flex-shrink:0;display:flex;flex-direction:column;background:rgba(0,0,0,.55);border-right:1px solid rgba(0,255,255,.12);overflow:hidden}}
.lib-header{{padding:8px 10px 6px;border-bottom:1px solid rgba(0,255,255,.1)}}
.lib-header h2{{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:rgba(0,255,255,.7);margin-bottom:6px}}
#searchInput{{width:100%;background:rgba(0,20,40,.9);border:1px solid rgba(0,255,255,.25);border-radius:4px;padding:6px 8px;color:#0ff;font-family:inherit;font-size:12px;outline:none}}
#searchInput::placeholder{{color:rgba(0,255,255,.35)}}
#searchInput:focus{{border-color:rgba(0,255,255,.6);box-shadow:0 0 8px rgba(0,255,255,.15)}}
.lib-scroll{{flex:1;overflow-y:auto;padding:4px 0}}
.lib-scroll::-webkit-scrollbar{{width:6px}}
.lib-scroll::-webkit-scrollbar-track{{background:transparent}}
.lib-scroll::-webkit-scrollbar-thumb{{background:rgba(0,255,255,.2);border-radius:3px}}
.genre-section{{margin-bottom:2px}}
.genre-header{{display:flex;align-items:center;gap:6px;padding:6px 10px;cursor:pointer;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:rgba(0,255,255,.75);background:rgba(0,30,60,.5);border-bottom:1px solid rgba(0,255,255,.06);user-select:none;transition:background .15s}}
.genre-header:hover{{background:rgba(0,40,80,.6)}}
.genre-header .arrow{{font-size:8px;transition:transform .2s}}
.genre-header.open .arrow{{transform:rotate(90deg)}}
.genre-header .cnt{{margin-left:auto;font-size:10px;color:rgba(0,255,255,.4)}}
.genre-games{{display:none;padding:2px 0}}
.genre-header.open+.genre-games{{display:block}}
.game-tile{{display:flex;align-items:center;gap:8px;padding:5px 10px 5px 18px;cursor:pointer;border-left:3px solid transparent;transition:background .12s,border-color .12s;font-size:12px;color:rgba(255,255,255,.8)}}
.game-tile:hover{{background:rgba(0,255,255,.06);border-left-color:rgba(0,255,255,.3)}}
.game-tile.active{{border-left-color:rgba(57,255,20,.75);background:rgba(57,255,20,.06);box-shadow:inset 0 0 12px rgba(57,255,20,.05)}}
.game-tile.active .gt-name::after{{content:' \\2605';color:rgba(57,255,20,.8)}}
.game-tile img.wheel-thumb{{width:32px;height:32px;object-fit:contain;border-radius:2px;flex-shrink:0;image-rendering:auto}}
.game-tile .gt-info{{flex:1;min-width:0}}
.game-tile .gt-name{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px;color:#e0f0ff}}
.game-tile .gt-year{{font-size:9px;color:rgba(0,255,255,.4)}}
.wheel-placeholder{{width:32px;height:32px;background:rgba(0,255,255,.08);border-radius:2px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:rgba(0,255,255,.25)}}
#libStatus{{padding:6px 10px;font-size:10px;color:rgba(0,255,255,.4);border-top:1px solid rgba(0,255,255,.06)}}

/* --- Center viewport --- */
.game-wrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:6px;background:#000}}
.game-wrap img{{width:100%;max-height:82vh;object-fit:contain;image-rendering:pixelated;border:1px solid rgba(0,255,255,.2);box-shadow:0 0 40px rgba(0,255,255,.08)}}

/* --- Right metrics panel --- */
.panel.right{{width:200px;flex-shrink:0;display:flex;flex-direction:column;gap:7px;padding:10px;background:rgba(0,0,0,.55);border-left:1px solid rgba(0,255,255,.12)}}
.card{{background:rgba(0,20,40,.75);border:1px solid rgba(0,255,255,.16);border-radius:4px;padding:7px 9px}}
.card .lbl{{font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(0,255,255,.6);margin-bottom:3px}}
.card .val{{font-size:22px;color:#0ff;text-shadow:0 0 10px rgba(0,255,255,.5);line-height:1.1}}
.card .sub{{font-size:10px;color:rgba(0,255,255,.5);margin-top:2px}}
#gameSwitchStatus{{min-height:1.2em}}

/* --- Header / audio / status --- */
header{{display:flex;align-items:center;justify-content:space-between;padding:6px 14px;background:rgba(0,0,0,.85);border-bottom:1px solid rgba(0,255,255,.12)}}
header h1{{font-size:12px;letter-spacing:3px;text-transform:uppercase}}
header a{{color:#555;font-size:11px;text-decoration:none}}header a:hover{{color:#0ff}}
.status{{display:flex;align-items:center;gap:6px;font-size:11px}}
.dot{{width:7px;height:7px;border-radius:50%;background:#0f0;box-shadow:0 0 6px #0f0;transition:background .3s}}
.audio-bar{{display:flex;align-items:center;gap:10px;padding:5px 14px;background:rgba(0,0,0,.85);border-top:1px solid rgba(0,255,255,.1);font-size:11px;color:rgba(0,255,255,.7)}}
#trackName{{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.ab{{background:none;border:1px solid rgba(0,255,255,.3);color:#0ff;border-radius:999px;padding:3px 10px;font-size:11px;cursor:pointer;font-family:inherit}}
.ab:hover{{border-color:#0ff;box-shadow:0 0 8px rgba(0,255,255,.25)}}

@media(max-width:900px){{
  .layout{{flex-direction:column}}
  .panel.left{{width:100%;max-height:40vh;border-right:none;border-bottom:1px solid rgba(0,255,255,.1)}}
  .panel.right{{width:100%;flex-direction:row;flex-wrap:wrap;gap:6px;border-left:none;border-top:1px solid rgba(0,255,255,.1)}}
  .panel.right .card{{flex:1;min-width:120px}}
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
    <div class="lib-header">
      <h2>Library</h2>
      <input type="text" id="searchInput" placeholder="Search games..." autocomplete="off" />
    </div>
    <div class="lib-scroll" id="libScroll"></div>
    <div id="libStatus">Loading catalog...</div>
  </div>
  <div class="game-wrap"><img src="/stream" alt="Live game" /></div>
  <div class="panel right">
    <div class="card"><div class="lbl">Current Game</div><div class="val" id="currentGame">Arcade</div><div class="sub" id="gameSwitchStatus">Using local MAME_ROMS</div></div>
    <div class="card"><div class="lbl">FPS</div><div class="val" id="fps">-</div></div>
    <div class="card"><div class="lbl">Avg Level</div><div class="val" id="level">-</div><div class="sub" id="peakLvl"></div></div>
    <div class="card"><div class="lbl">Clients</div><div class="val" id="clnts">-</div></div>
    <div class="card"><div class="lbl">Reward 1M</div><div class="val" id="rew">-</div></div>
    <div class="card"><div class="lbl">High Score</div><div class="val" id="hi">-</div></div>
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
const CATALOG_URL='/api/catalog?parents_only=1&launchable_only=1';
let tracks=[],idx=0,enabled=false;
let currentGame={json.dumps(DEFAULT_VIEWPORT_GAME)};
let catalogGames=[];
let genreMap={{}};
const audio=document.getElementById('bgAudio');
const statusEl=document.getElementById('gameSwitchStatus');
const currentGameEl=document.getElementById('currentGame');
const titleGameEl=document.getElementById('liveTitleGame');
const libScroll=document.getElementById('libScroll');
const libStatus=document.getElementById('libStatus');
const searchInput=document.getElementById('searchInput');

/* --- Audio --- */
async function loadPL(){{try{{const r=await fetch(PLAYLIST);const d=await r.json();tracks=d.tracks||[];if(tracks.length)setTrack(0);}}catch(e){{}}}}
function setTrack(i){{if(!tracks.length)return;idx=(i+tracks.length)%tracks.length;audio.src=tracks[idx].url;document.getElementById('trackName').textContent=tracks[idx].name;if(enabled)audio.play().catch(()=>{{}});}}
function toggleAudio(){{enabled=!enabled;document.getElementById('playBtn').textContent=enabled?'\\u23f8 Audio':'\\u25b6 Audio';if(enabled)audio.play().catch(()=>{{}});else audio.pause();}}
function nextTrack(){{setTrack(idx+1);}}
audio.addEventListener('ended',()=>setTrack(idx+1));

/* --- Formatting --- */
function fmt(v,d=0){{if(v===null||v===undefined)return'-';const n=Number(v);if(isNaN(n))return'-';if(Math.abs(n)>=1e6)return(n/1e6).toFixed(1)+'M';if(Math.abs(n)>=1e3)return(n/1e3).toFixed(1)+'K';return n.toFixed(d);}}

/* --- Game state --- */
function syncSelectedGame(game){{
  currentGame=game;
  const desc=gameDescMap[game]||game;
  currentGameEl.textContent=desc;
  titleGameEl.textContent=desc;
  document.title=desc+' AI \\u2014 Live';
  document.querySelectorAll('.game-tile').forEach(el=>el.classList.toggle('active',el.dataset.game===game));
}}
let gameDescMap={{}};

/* --- Library catalog --- */
function savedAccordion(){{try{{return JSON.parse(localStorage.getItem('genreAccState')||'{{}}')}}catch(e){{return {{}}}}}}
function saveAccordion(state){{try{{localStorage.setItem('genreAccState',JSON.stringify(state))}}catch(e){{}}}}

async function loadCatalog(){{
  try{{
    const r=await fetch(CATALOG_URL+'&per_page=50000&t='+Date.now(),{{cache:'no-store'}});
    const d=await r.json();
    catalogGames=d.games||[];
    genreMap={{}};
    gameDescMap={{}};
    catalogGames.forEach(g=>{{
      gameDescMap[g.game_id]=g.description||g.game_id;
      const genre=g.genre||'Uncategorized';
      if(!genreMap[genre])genreMap[genre]=[];
      genreMap[genre].push(g);
    }});
    renderLibrary(catalogGames);
    libStatus.textContent=catalogGames.length+' games loaded';
  }}catch(e){{
    libStatus.textContent='Catalog unavailable';
  }}
}}

function renderLibrary(games){{
  const byGenre={{}};
  games.forEach(g=>{{
    const genre=g.genre||'Uncategorized';
    if(!byGenre[genre])byGenre[genre]=[];
    byGenre[genre].push(g);
  }});
  const accState=savedAccordion();
  const genres=Object.keys(byGenre).sort();
  let html='';
  genres.forEach(genre=>{{
    const open=accState[genre]!==false;
    const list=byGenre[genre];
    html+='<div class="genre-section">';
    html+='<div class="genre-header'+(open?' open':'')+'" data-genre="'+genre+'">';
    html+='<span class="arrow">\\u25B6</span> '+genre;
    html+='<span class="cnt">('+list.length+')</span></div>';
    html+='<div class="genre-games">';
    list.forEach(g=>{{
      const isActive=g.game_id===currentGame;
      const wheelSrc='/assets/wheel/'+g.game_id+'.png';
      html+='<div class="game-tile'+(isActive?' active':'')+'" data-game="'+g.game_id+'" onclick="selectGame(\''+g.game_id+'\')">';
      html+='<img class="wheel-thumb" src="'+wheelSrc+'" loading="lazy" onerror="this.outerHTML=\'<div class=wheel-placeholder>\\u25CE</div>\'" />';
      html+='<div class="gt-info"><span class="gt-name">'+((g.description||g.game_id).replace(/</g,'&lt;'))+'</span>';
      if(g.year||g.manufacturer)html+='<span class="gt-year">'+(g.year||'')+' '+(g.manufacturer||'')+'</span>';
      html+='</div></div>';
    }});
    html+='</div></div>';
  }});
  libScroll.innerHTML=html;
  libScroll.querySelectorAll('.genre-header').forEach(hdr=>{{
    hdr.addEventListener('click',()=>{{
      hdr.classList.toggle('open');
      const st=savedAccordion();
      st[hdr.dataset.genre]=hdr.classList.contains('open');
      saveAccordion(st);
    }});
  }});
}}

/* --- Search (debounced) --- */
let searchTimer=null;
searchInput.addEventListener('input',()=>{{
  clearTimeout(searchTimer);
  searchTimer=setTimeout(()=>{{
    const q=searchInput.value.trim().toLowerCase();
    if(!q){{renderLibrary(catalogGames);libStatus.textContent=catalogGames.length+' games';return;}}
    const filtered=catalogGames.filter(g=>{{
      return (g.description||'').toLowerCase().includes(q)
        || (g.game_id||'').toLowerCase().includes(q)
        || (g.manufacturer||'').toLowerCase().includes(q);
    }});
    renderLibrary(filtered);
    libStatus.textContent=filtered.length+' of '+catalogGames.length+' games';
  }},300);
}});

/* --- Game selection --- */
async function selectGame(game){{
  statusEl.textContent='Switching viewport to '+(gameDescMap[game]||game)+'...';
  try{{
    const r=await fetch(SELECT_GAME,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{selected_game:game}})}});
    const d=await r.json();
    syncSelectedGame(d.selected_game||game);
    statusEl.textContent=d.message||('Viewport loaded '+(gameDescMap[d.selected_game||game]||game));
  }}catch(e){{
    statusEl.textContent='Viewport switch failed';
  }}
}}

async function refreshGameSettings(){{try{{const r=await fetch(GAME_SETTINGS+'?t='+Date.now(),{{cache:'no-store'}});const d=await r.json();if(d.selected_game)syncSelectedGame(d.selected_game);}}catch(e){{}}}}

/* --- Metrics polling --- */
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

/* --- Boot --- */
loadPL();refreshGameSettings();loadCatalog();poll();setInterval(poll,1500);
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
    return method, path, body, target


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


def launch_viewport_game(game_id_raw):
    catalog = get_catalog()
    game_id = str(game_id_raw).strip().lower()

    if not catalog.is_launchable(game_id):
        return None, f"Game '{game_id}' not found or no ROM available"

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
    if _game_uses_lua(game_id):
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
    return proc.pid, None


def ensure_viewport_game_running():
    if list(iter_visible_mame_pids()):
        return
    pid, err = launch_viewport_game(load_selected_game())
    if err:
        print(f"Warning: could not launch viewport game: {err}", flush=True)


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
    game_id = str(payload.get("selected_game", "")).strip().lower()
    if not game_id:
        send_response(conn, 400, b'{"error":"missing selected_game"}', b"application/json")
        return
    game_id = save_selected_game(game_id)
    try:
        proxy_post_settings({"selected_game": game_id})
    except Exception:
        pass
    pid, err = launch_viewport_game(game_id)
    if err:
        response = {"selected_game": game_id, "error": err}
        send_response(conn, 400, json.dumps(response).encode("utf-8"), b"application/json")
    else:
        catalog = get_catalog()
        entry = catalog.games.get(game_id)
        label = entry.description if entry else game_id
        response = {
            "selected_game": game_id,
            "message": f"Viewport switched to {label} (PID {pid})",
        }
        send_response(conn, 200, json.dumps(response).encode("utf-8"), b"application/json")


def _parse_qs(target):
    """Parse query string from a request target into a dict."""
    if "?" not in target:
        return {}
    qs = target.split("?", 1)[1]
    params = {}
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[urllib.parse.unquote_plus(k)] = urllib.parse.unquote_plus(v)
    return params


def _serve_file(conn, file_path, content_type, cache_control=b"public, max-age=86400"):
    """Serve a file from disk with caching headers."""
    if not os.path.isfile(file_path):
        send_response(conn, 404, b'{"error":"not found"}', b"application/json")
        return
    with open(file_path, "rb") as fh:
        data = fh.read()
    reasons = {200: b"OK"}
    headers = [
        b"HTTP/1.1 200 OK",
        b"Content-Type: " + content_type,
        b"Content-Length: " + str(len(data)).encode(),
        b"Cache-Control: " + cache_control,
        b"Access-Control-Allow-Origin: *",
    ]
    conn.sendall(b"\r\n".join(headers) + b"\r\n\r\n" + data)


def handle_catalog_api(conn, target):
    """Handle /api/catalog with filtering, search, and pagination."""
    params = _parse_qs(target)
    catalog = get_catalog()
    parents_only = params.get("parents_only", "") == "1"
    launchable_only = params.get("launchable_only", "") == "1"
    genre = params.get("genre", "").strip()
    query = params.get("q", "").strip()

    if query:
        games = catalog.search(query, parents_only=parents_only, launchable_only=launchable_only)
    elif genre:
        games = catalog.get_genre(genre, parents_only=parents_only, launchable_only=launchable_only)
    elif launchable_only:
        games = catalog.get_launchable(parents_only=parents_only)
    else:
        games = list(catalog.games.values())
        if parents_only:
            games = [g for g in games if g.is_parent]

    total = len(games)
    page = max(1, int(params.get("page", "1")))
    per_page = min(50000, max(1, int(params.get("per_page", "50000"))))
    start = (page - 1) * per_page
    page_games = games[start:start + per_page]

    result = {
        "games": catalog.to_json_list(page_games),
        "total": total,
        "page": page,
        "per_page": per_page,
    }
    send_response(conn, 200, json.dumps(result).encode("utf-8"), b"application/json")


def handle_genres_api(conn):
    """Handle /api/genres."""
    catalog = get_catalog()
    result = {"genres": catalog.genre_summary()}
    send_response(conn, 200, json.dumps(result).encode("utf-8"), b"application/json")


def handle_asset_wheel(conn, path):
    """Serve wheel art: /assets/wheel/{game_id}.png"""
    game_id = path.rsplit("/", 1)[-1]
    if not game_id.endswith(".png"):
        send_response(conn, 404, b'{"error":"not found"}', b"application/json")
        return
    game_id = game_id[:-4]
    file_path = os.path.join(MAME_FRONTEND, "Images", "Wheel", f"{game_id}.png")
    _serve_file(conn, file_path, b"image/png")


def handle_asset_video(conn, path):
    """Serve preview video: /assets/video/{game_id}.flv"""
    game_id = path.rsplit("/", 1)[-1]
    if not game_id.endswith(".flv"):
        send_response(conn, 404, b'{"error":"not found"}', b"application/json")
        return
    game_id = game_id[:-4]
    # Check flat path first, then letter-based subdirectory
    file_path = os.path.join(MAME_FRONTEND, "Video", f"{game_id}.flv")
    if not os.path.isfile(file_path) and game_id:
        letter = game_id[0].upper()
        file_path = os.path.join(MAME_FRONTEND, "Video", letter, f"{game_id}.flv")
    _serve_file(conn, file_path, b"video/x-flv")


def handle_asset_genre_wheel(conn, path):
    """Serve genre wheel art: /assets/genre/wheel/{genre_name}.png"""
    filename = path.rsplit("/", 1)[-1]
    if not filename.endswith(".png"):
        send_response(conn, 404, b'{"error":"not found"}', b"application/json")
        return
    genre_name = urllib.parse.unquote(filename[:-4])
    file_path = os.path.join(MAME_FRONTEND, "Images", "Genre", "Wheel", f"{genre_name}.png")
    _serve_file(conn, file_path, b"image/png")


def handle_client(conn):
    try:
        request = read_request(conn)
        if not request:
            conn.close()
            return
        method, path, body, target = request
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

        # --- Asset serving routes ---
        if path.startswith("/assets/genre/wheel/"):
            handle_asset_genre_wheel(conn, path)
            conn.close()
            return
        if path.startswith("/assets/wheel/"):
            handle_asset_wheel(conn, path)
            conn.close()
            return
        if path.startswith("/assets/video/"):
            handle_asset_video(conn, path)
            conn.close()
            return

        # --- API routes ---
        if path == "/api/select_game":
            if method != "POST":
                send_response(conn, 405, b'{"error":"method not allowed"}', b"application/json")
            else:
                handle_select_game(conn, body)
            conn.close()
            return
        if path == "/api/catalog":
            if method != "GET":
                send_response(conn, 405, b'{"error":"method not allowed"}', b"application/json")
            else:
                handle_catalog_api(conn, target)
            conn.close()
            return
        if path == "/api/genres":
            if method != "GET":
                send_response(conn, 405, b'{"error":"method not allowed"}', b"application/json")
            else:
                handle_genres_api(conn)
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
