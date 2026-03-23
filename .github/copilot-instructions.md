# Copilot Instructions — Tempest AI

## What This Repository Is

Tempest AI is a **reinforcement learning system** that trains a neural network to play Atari's *Tempest* (1981 arcade game) inside the MAME emulator. The agent uses a Rainbow DQN variant (distributional C51, prioritized experience replay, dueling networks, multi-head self-attention, N-step returns, and behavioral cloning from a hand-coded expert system).

---

## Repository Layout

```
.
├── Scripts/                  # Core application code — edit most here
│   ├── main.py               # Entry point; boots TCP server + threads
│   ├── config.py             # ALL hyperparameters and constants — single source of truth
│   ├── aimodel.py            # RainbowAgent class (network definition, forward pass, action selection)
│   ├── training.py           # train_step() — C51 Bellman update + PER weight correction
│   ├── replay_buffer.py      # AsyncReplayBuffer with sum-tree PER
│   ├── socket_server.py      # TCP server (Lua ↔ Python bridge, port 9999)
│   ├── nstep_buffer.py       # N-step return accumulator
│   ├── metrics_dashboard.py  # Web dashboard at http://localhost:8765
│   ├── metrics_display.py    # Terminal metrics display
│   ├── main.lua              # MAME autoboot script (frame callback entry)
│   ├── state.lua             # Reads ~80 MAME memory addresses → 195-float state vector
│   ├── logic.lua             # Expert system (hand-coded Tempest strategy)
│   ├── display.lua           # On-screen HUD rendering inside MAME
│   ├── test_pipeline.py      # Quick integration smoke-test (no MAME needed)
│   └── nstep_smoketest.py    # N-step buffer integration test
├── tests/                    # pytest test suite
│   ├── test_state_extraction.py
│   ├── test_enemy_slot_masking.py
│   ├── test_pre_death_sampling.py
│   ├── test_avoidance_logic.py
│   ├── test_superzap_penalty.py
│   └── lua/                  # Lua unit tests
├── models/                   # Saved checkpoints (not committed — see .gitignore)
│   └── tempest_model_latest.pt
├── Code/Atari/               # Original 6502 Tempest assembly (reference only)
├── tools/                    # Build tools for Atari assembly
├── LUAScripts/               # Extra MAME Lua utilities
├── docs/                     # GitHub Pages site source
├── requirements.txt          # Python dependencies
├── startmame.sh / startmame.cmd  # Launch MAME instances
└── README.md                 # Full architecture documentation
```

---

## Key Conventions

### 1. Central Configuration (`Scripts/config.py`)
- **All** hyperparameters, server settings, and constants live in `config.py`.
- Dataclasses: `ServerConfigData` (server), `RLConfigData` (RL), `MetricsData` (metrics).
- Singletons: `SERVER_CONFIG`, `RL_CONFIG`, `METRICS`.
- **Never hardcode** a hyperparameter in `aimodel.py`, `training.py`, or `socket_server.py` — always read from `config.py`.

### 2. State Vector (195 floats)
- Defined in `Scripts/state.lua` and consumed in `Scripts/aimodel.py` (`parse_frame_data()`).
- Includes: player position, 7 enemy slots (type/depth/segment/velocity/alive/fuseballFlags), shot positions, spike heights, level info, score, lives, etc.
- `RL_CONFIG.state_size = 195` and `SERVER_CONFIG.params_count = 195` must stay in sync.

### 3. Factored Action Space
- Actions are two independent heads: **fire/zap** (4 values) × **spinner** (11 levels) = 44 joint actions.
- Spinner levels are defined in `RL_CONFIG.spinner_command_levels`.
- `encode_action_to_game()` in `aimodel.py` converts joint index → 3-byte control message for Lua.

### 4. Rainbow DQN Architecture (`Scripts/aimodel.py`)
- `RainbowAgent` contains the full model, optimizer, target network, and inference logic.
- Distributional (C51): 51 atoms, support `[v_min, v_max]` = `[-100.0, 100.0]`.
- Multi-head self-attention over the 7 enemy slots before the trunk network.
- Dueling streams: value + advantage, combined to Q-distribution.
- Expert behavioral-cloning loss is mixed with the Bellman loss during early training.

### 5. Training (`Scripts/training.py`)
- `train_step(agent, replay_buffer, device)` runs one gradient update.
- Uses **prioritized importance-sampling weights** from `AsyncReplayBuffer.sample()`.
- Priorities are updated after each step via `replay_buffer.update_priorities()`.
- Learning rate follows a cosine schedule with warm restarts (period: `lr_cosine_period`).

### 6. Replay Buffer (`Scripts/replay_buffer.py`)
- Sum-tree data structure for O(log N) priority sampling.
- `AsyncReplayBuffer` wraps the buffer with a thread-safe queue for async pushes from the socket server.
- Pre-death boosting: the 120 frames before any death get priority multiplied by `PRE_DEATH_PRIORITY_BOOST`.

### 7. Socket Protocol
- **Lua → Python**: fixed-length binary message: 195 floats + reward float + episode flags.
- **Python → Lua**: 3 bytes (fire/zap byte, spinner byte, superzapper byte).
- Server port: `9999` (configurable via `SERVER_CONFIG.port`).
- Up to 36 parallel MAME instances (`SERVER_CONFIG.max_clients`).

---

## How to Run

### Prerequisites
```bash
pip install -r requirements.txt   # numpy, torch, pytest, matplotlib
# MAME must be installed separately (not in repo — requires ROM file)
```

### Start the Training Server
```bash
cd Scripts/
python3 main.py
```
- Listens on `0.0.0.0:9999`
- Loads `models/tempest_model_latest.pt` if it exists
- Dashboard auto-opens at `http://127.0.0.1:8765`

### Launch MAME Instances (separate terminal)
```bash
# Linux / macOS
./startmame.sh 4       # Launch 4 MAME instances
./startmame.sh -kill   # Kill all instances

# Windows
startmame.cmd          # Launches 16 instances
stopmame.cmd
```

### Environment Flags
| Variable | Default | Effect |
|---|---|---|
| `TEMPEST_DASHBOARD` | `1` | Set to `0` to disable the web dashboard |
| `TEMPEST_DASHBOARD_BROWSER` | `1` | Set to `0` to prevent auto-opening browser |
| `TEMPEST_DASHBOARD_PORT` | `8765` | Override dashboard port |

---

## Testing

```bash
# Run all tests (from repo root)
pytest tests/

# Run individual tests
pytest tests/test_state_extraction.py
pytest tests/test_enemy_slot_masking.py
pytest tests/test_pre_death_sampling.py
pytest tests/test_avoidance_logic.py
pytest tests/test_superzap_penalty.py

# Integration smoke tests (no MAME required)
python3 Scripts/test_pipeline.py
python3 Scripts/nstep_smoketest.py
```

- Tests are in `tests/` (pytest) and `Scripts/test_pipeline.py` / `Scripts/nstep_smoketest.py`.
- There is **no linting configuration** in this repo. Don't add linting steps unless asked.
- Tests do **not** require MAME or a GPU — they stub out the socket server and model inference.

---

## Common Tasks for a Coding Agent

### Modifying a Hyperparameter
1. Open `Scripts/config.py`.
2. Locate the relevant `@dataclass` (`RLConfigData` for RL, `ServerConfigData` for server).
3. Change the value there — it propagates automatically everywhere.

### Adding a New Feature to the Neural Network
1. Edit `Scripts/aimodel.py` — the `RainbowAgent` class.
2. If new hyperparameters are needed, add them to `RLConfigData` in `Scripts/config.py` first.
3. Run `pytest tests/` to confirm existing tests still pass.

### Adding a New Test
- Place Python tests in `tests/test_<feature>.py` using `pytest` conventions.
- Place Lua tests in `tests/lua/`.
- Tests should not require MAME, a ROM file, or a trained model checkpoint.
- Mock or stub `Scripts/socket_server.py` and `Scripts/aimodel.py` where needed.

### Changing the State Vector
1. Update memory reads in `Scripts/state.lua`.
2. Update `parse_frame_data()` in `Scripts/aimodel.py`.
3. Update `SERVER_CONFIG.params_count` and `RL_CONFIG.state_size` in `Scripts/config.py`.
4. Re-verify the 195-float count is consistent across all three files.

### Modifying Reward Logic
- **Objective reward**: computed in `Scripts/state.lua` (score deltas).
- **Subjective reward**: computed in `Scripts/logic.lua` (positioning quality).
- Both signals are sent as part of the Lua → Python frame payload.

### Adding a New Metric to the Dashboard
1. Add the metric field to `MetricsData` in `Scripts/config.py`.
2. Update the collection point in `Scripts/socket_server.py` or `Scripts/training.py`.
3. Add the rendering in `Scripts/metrics_dashboard.py` and/or `Scripts/metrics_display.py`.

---

## Architecture Quick Reference

```
MAME (Lua)  ──[TCP 9999]──▶  SocketServer  ──▶  AsyncReplayBuffer
                                  │                    │
                                  │ inference          │ batches
                                  ▼                    ▼
                             RainbowAgent  ◀──── train_step()
                             (aimodel.py)        (training.py)
```

| Component | File | Key Class/Function |
|---|---|---|
| Config | `Scripts/config.py` | `RL_CONFIG`, `SERVER_CONFIG` |
| Agent | `Scripts/aimodel.py` | `RainbowAgent` |
| Training | `Scripts/training.py` | `train_step()` |
| Replay | `Scripts/replay_buffer.py` | `AsyncReplayBuffer` |
| Server | `Scripts/socket_server.py` | `SocketServer` |
| N-step | `Scripts/nstep_buffer.py` | `NStepBuffer` |
| Dashboard | `Scripts/metrics_dashboard.py` | web server on port 8765 |
| State (Lua) | `Scripts/state.lua` | `getState()` |
| Expert (Lua) | `Scripts/logic.lua` | `getAction()` |
| Entry (Lua) | `Scripts/main.lua` | frame callback |

---

## Important Files NOT in the Repo

| File | Reason |
|---|---|
| `models/tempest_model_latest.pt` | Large binary; excluded by `.gitignore` |
| `models/game_settings.json` | Runtime-generated settings |
| MAME binary | Must be installed separately |
| Tempest ROM (`tempest.zip`) | Copyrighted; excluded by `.gitignore` |
| `*.log` files | Runtime logs; excluded by `.gitignore` |

---

## Known Workarounds & Gotchas

- **`tile.py`** uses `pywin32` which is Windows-only. Don't import it on Linux/macOS.
- **`tools/hxa65w.exe`** is a Windows assembler binary. Running it on Linux requires Wine.
- **Port 9999** must be free before starting `main.py`. If it's in use, change `SERVER_CONFIG.port` in `config.py`.
- **PyTorch CUDA**: The training loop uses `torch.cuda.is_available()` — on CPU-only machines it falls back gracefully but is much slower.
- **Model loading**: If `models/tempest_model_latest.pt` has a different architecture than the current config, the load will fail. Set `FORCE_FRESH_MODEL = True` in `config.py` to start from scratch.
- **MAME Lua path**: MAME expects the autoboot script path relative to the MAME working directory. The `startmame.sh` / `startmame.cmd` scripts handle this automatically.
- **Multiple clients**: Each MAME instance connects independently. The server assigns client IDs and aggregates experience across all sessions.
