# ghosthands

**Give an AI agent real hands and eyes.** ghosthands drives a *real* computer screen the way a
person does: it looks at the screen, decides what to do, and moves a real mouse and keyboard over
**USB HID** — independent of browser DOM and accessibility APIs, so it can work with native apps
as well as browsers.

It is three cheap parts:

| Part | Role | Default |
|------|------|---------|
| 🧠 **Brain** | a small *vision* LLM that sees the screen and picks the next action | `z-ai/glm-5.3-flash` |
| 👁️ **Eyes** | a GUI *grounding* model that turns "click the blue Create button" into an (x, y) | `bytedance/ui-tars-1.5-7b` |
| ✋ **Hands** | a tiny RP2040 board flashed as a USB-HID mouse+keyboard | dry-run; QT Py/XIAO for live input |

Both models run over any OpenAI-compatible endpoint (OpenRouter by default). A full step —
screenshot → decide → locate → click — costs roughly **$0.0002**. The expensive frontier model
that *orchestrated* the task is out of the loop; the loop runs on nickels.

## Why real HID instead of software automation

- **Hardware-level input.** It avoids `WebDriver`, synthetic-event, and accessibility APIs. This
  does not make behaviour undetectable: applications and services can still infer automation.
- **DOM-independent.** It reads *pixels*, not HTML. It drives native apps, Electron, games,
  remote desktops, a BIOS screen — anything with a display.
- **Cheap brain.** Grounding + a small vision planner replace an expensive agent doing per-frame
  reasoning. You supervise; the nickels drive.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export OPENROUTER_API_KEY=sk-or-...

# 1) Build the USB-C hands (see docs/HARDWARE.md):
scripts/flash-board.sh qtpy-rp2040                    # plan only
scripts/flash-board.sh qtpy-rp2040 --write            # explicit hardware write
ghosthands --doctor --ping

# 2) Start the eyes IN A GUI TERMINAL (macOS screen-recording grant must attach):
bash scripts/screenfeed.sh

# 3) Prove the hands work (no LLM):
python3 examples/trace_square.py --live

# 4) Preview a task with no real input (the default):
ghosthands --hands dryrun --goal "Open TextEdit and type hello" \
  --guide "Use Spotlight (cmd+space) to open TextEdit, then type."

# 5) Only after reviewing the goal, enable the real HID board:
ghosthands --hands pico --live --goal "Open TextEdit and type hello" \
  --guide "Use Spotlight (cmd+space) to open TextEdit, then type."
```

## How the loop works

```
  capture screen ──▶ BRAIN (vision LLM) picks ONE action as JSON
        ▲                         │
        │              ┌──────────┴───────────┐
        │           click?                  type/key/scroll/navigate/wait
        │              │                        │
        │          EYES (grounding model)       │
        │        "the X" ──▶ (x, y) fraction    │
        │              │                        │
        └────────── HANDS (RP2040 USB-HID) ◀──────┘
```

Every step is logged to `~/gh-runs/<run>/log.jsonl` with a screenshot per step. The brain pauses
at **money checkpoints** (see Safety) so a human can eyeball an irreversible click.

## Safety

- The planner is instructed never to commit a price/charge until it has read the value back and
  confirmed it. When it wants a human to look, it emits `verify_stop`; the agent pauses and waits
  for you to `touch <run_dir>/CONTINUE` (or `ABORT`).
- Real HID means real consequences: it can click anything on your screen. Dry-run is the default;
  live input requires both `--hands pico` and `--live`. Keep the printed `ABORT` path handy.
- Screenshots are sent to the configured model provider and retained in the local run directory.
- This is an automation tool. Respect the terms of service of whatever you point it at.

## Layout

```
ghosthands/        core library  (config, eyes, hands, brain, agent)
run.py             CLI
examples/          trace_square.py, streamon3_subscriptions.py
scripts/           screenfeed.sh (the eyes) + firmware/ (the hands)
hardware/          printable XIAO RP2040 enclosure + reproducible CAD source
docs/              HARDWARE.md, ARCHITECTURE.md
```

MIT licensed. Built as the screen-driving component behind AppSpace's autonomous ops.
