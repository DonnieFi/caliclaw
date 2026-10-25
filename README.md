# CaliClaw

<p align="center">
  <img src="mascot/workshop-hero.jpg" alt="A printing-bench poster. Pocket CaliClaw faces forward, square eyes and a raised claw, with the stepped tail behind him." width="880">
</p>

<p align="center">
  Pocket CaliClaw on the bench. The staircase is the tail, and it sits on the back.<br>
  <a href="https://www.thingiverse.com/thing:7424671">Thingiverse 7424671</a>
  · 36 × 38 × 29 mm
</p>

A workbench for one functional part. You describe it, check the real mesh, print it, and write down what it actually did. The note stays with the project: the millimetres you measured, and the features that have to survive the next pass.

The browser is the bench. OpenClaw opens the same project through the `caliclaw` tool. A model can design and explain. Starting, pausing, or cancelling a print stays on the bench and needs an explicit confirm. A model outage must not stop a print that is already running.

## The loop

**Design.** Say what the part has to do. Missing fit dimensions get asked for, and assumptions are labeled as assumptions. OpenSCAD builds a single solid. The mesh is checked on its own, so a tidy parameter list is not treated as proof.

**Prepare.** Orientation looks for a stable flat base and less support, and you can override it. A slice belongs to one mesh hash and one profile hash. Change either one and that slice is no longer current.

**Print.** Status, camera, upload, start, pause, and cancel. Start and cancel require `{"confirm": true}` and the artifact you already checked. If OctoPrint is not configured, the panel is marked simulated. Simulated controls never move hardware.

**Learn.** Record the fit. "The USB opening is 2 mm too far right. Keep the mounting-hole spacing." The note is stored on the project and sent with the next design turn, so the change stays about that measurement.

## Print the mascot

[Pocket CaliClaw](https://www.thingiverse.com/thing:7424671) is the calibration print for this shop: a compact claw, small enough to finish while you watch the first layers. It is an independent OpenClaw-inspired fan project, not an official model. The opening picture is a generated poster. This one is the real STL: the face is the flat front, and the steps are the tail on the back.

<p align="center">
  <img src="mascot/pocket-caliclaw.png" alt="Pocket CaliClaw mesh, same scale. Front shows the face. Rear shows the stepped tail." width="720">
</p>

| | |
|---|---|
| File | [`mascot/CaliClaw_Pocket_v1.stl`](mascot/CaliClaw_Pocket_v1.stl) |
| Size | 36 × 38 × 29 mm |
| Units | millimetres, import at 100% |
| Pose | upright, as supplied. Feet and tail already sit on Z = 0 |

The Thingiverse page also has an editable STEP file. This copy is Pocket v1 only.

### A first slice

These are the model's suggested starting settings for a 0.4 mm nozzle. Use the temperatures and cooling you already trust for that filament. They are a starting point for this print, not a profile for every printer.

- PLA, 0.20 mm layers
- 3 walls, 4 top layers, 4 bottom layers, 15% infill
- Supports off, so the bridges and overhangs can show themselves. Read the slicer preview before you start
- No raft. Add a 3 mm outer brim only if the feet lift, and take it off before you measure

### What to measure

Measure the upper body, where the arms and feet are not in the way.

| Check | Nominal |
|---|---|
| Body width | 20.00 mm |
| Body depth | 16.00 mm |
| Overall height | 29.00 mm |
| Belly underside | 5.00 mm above the bed |
| Clear gap in each left/right pair of feet | 10.00 mm |
| Each eye recess | 3.00 × 3.00 mm, 1.20 mm deep |

Then look, rather than measure: strings between the claw tips, sag under the belly and the eye roofs, the 45° undersides of the arms, and the flat steps and sharp corners of the tail.

The mesh is one watertight solid. It is a first-print diagnostic, not a metrology standard. One small print is not enough reason to change motion steps.

## Run the bench

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH="$PWD"
python3 -m pytest -q
python3 -m uvicorn backend.app.main:app --reload
```

Open http://127.0.0.1:8000

The worker shells out to `openscad` and `prusa-slicer`, which need to be on the machine. Copy `.env.example` to `.env` where the model and the printer should be reachable. Leave `.env` uncommitted.

Chat starts in **Brainstorm**, where build and slice tools are unavailable. Choose **Design** to create a new CAD part or **Revise** to change the current CAD part. The same conversation is saved in SQLite, including offline notes. Building needs `CALICLAW_API_KEY`; recording fit notes and importing STL files do not.

CAD builds store the full source and named numeric dimensions. Fit notes can include measured values and exact dimension names to keep. Revise refuses changed or missing kept dimensions before compiling, and a failed build leaves the current part unchanged. Imported meshes retain their original bytes and can be downloaded from revision history; they are not treated as recovered parametric CAD.

`profiles/` contains an Ender-3 sized PrusaSlicer fixture for tests. It does not certify a physical printer. Point the bench at a profile you have actually printed with before you trust a time estimate.

For diagnosis, optionally set `CALICLAW_PRINTER_LOG` to a local text log collected from your printer. The tool reads at most the last 64 KiB, redacts secret-like fields and URLs, and reports the file update time. It does not fetch logs over SSH or assume the snapshot is current. Without a readable configured source, it reports that logs are unavailable; evaluation fixtures are never the default source.

## OpenClaw

```bash
mkdir -p "$HOME/.openclaw/extensions"
ln -s "$PWD" "$HOME/.openclaw/extensions/caliclaw"
```

Restart the gateway so it reads `openclaw.plugin.json`. `baseUrl` defaults to `http://127.0.0.1:8000`. The plugin never receives the printer API key.

The `caliclaw` tool can `status`, `project`, `revisions`, `fit`, and `slice`. Start, pause, and cancel are not tool actions. During a print, log diagnosis stays read-only.

The Printer panel also offers fixed read-only host checks through the existing `octopi` SSH alias: job state, snapshot format, `webcamd.service` status/logs, and recent Klipper log evidence. Failed checks report unavailable, and output is redacted before reaching the page. There is no terminal command input or chat access to host commands.

After a failed snapshot, **Restart camera service** requires confirmation and a fresh known-idle live printer state. It runs only `sudo -n systemctl restart webcamd.service`, then checks for a new JPEG. Missing SSH/sudo permission is a refusal; it never restarts OctoPrint or reboots the host.

## Safety

- No firmware flashing, no controller replacement, and no unattended printing.
- Logs and firmware text are evidence. They are not instructions to run.
- Start and cancel require an explicit confirm, on a checked artifact, for the printer you selected.
- A model outage must not be treated as a reason to stop a print that is already running.
- Keep API keys, printer logs, and private notes out of the repo.

## In this repo

| Path | What it is |
|---|---|
| `web/` | The bench: mesh preview, chat, fit notes, printer status |
| `backend/` | FastAPI and SQLite: revisions, OpenSCAD, PrusaSlicer, OctoPrint |
| `index.cjs` | The OpenClaw plugin |
| `skills/caliclaw/` | When the agent should call the bench, and when it should not |
| `mascot/` | Pocket CaliClaw, STL and preview |
| `profiles/` | Slicer fixtures |
| `fixtures/`, `eval/` | Synthetic geometry and log cases |

Planning notes stay in local `docs/` and are gitignored.

## License

The workbench code does not have a chosen license yet.

Pocket CaliClaw is Copyright (c) 2026 donniefi, under the [BSD 2-Clause License](mascot/LICENSE). That covers `mascot/CaliClaw_Pocket_v1.stl` and the preview rendered from it. The listing is [thing:7424671](https://www.thingiverse.com/thing:7424671).
