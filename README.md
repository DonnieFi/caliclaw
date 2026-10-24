# CaliClaw

A printing workbench for one functional part: describe it, check the mesh, print it, then record what the part actually did.

The next revision changes that measurement and leaves the kept features alone. OpenClaw reaches the same project through the `caliclaw` tool. The browser is the workbench. A model can design and explain. It does not start the printer, and a model outage does not stop a print that is already running.

This is the shop tool, not a contest entry. The name is the workshop calibration mascot.

## What this repo is

- `web/` is the workbench: STL preview, printer status, chat, and upload / start / pause / cancel.
- `backend/` is FastAPI and SQLite: revisions, an isolated OpenSCAD build, PrusaSlicer, an OctoPrint client, and a model tool loop.
- `openclaw.plugin.json` and `skills/caliclaw/` load the workshop rules into OpenClaw.
- `profiles/` holds an Ender-3 sized PrusaSlicer fixture. It does not certify a physical printer.
- `fixtures/` and `eval/` are synthetic cases. No personal logs.

Planning notes and imported conversations stay in local `docs/` and are gitignored.

## Run the webapp

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH="$PWD"
python3 -m pytest -q
python3 -m uvicorn backend.app.main:app --reload
```

Open http://127.0.0.1:8000

System packages used by the worker: `openscad` and `prusa-slicer`.

Copy `.env.example` to `.env` on the machine that should reach the model and the printer. Do not commit `.env`.

## Load the OpenClaw plugin

```bash
mkdir -p "$HOME/.openclaw/extensions"
ln -s "$PWD" "$HOME/.openclaw/extensions/caliclaw"
```

Restart the OpenClaw gateway so it reads `openclaw.plugin.json`. The skill tells the agent to call this workbench, keep log diagnosis read-only during a print, and require an explicit confirm before start or cancel.

`baseUrl` defaults to `http://127.0.0.1:8000`.

The tool actions are `status`, `project`, `revisions`, `fit`, and `slice`. `fit` stores a measurement and the features that must stay. Start and cancel are not tool actions.

## Printer controls

`GET /api/printer` is status. Start and cancel are `POST /api/printer/start` and `POST /api/printer/cancel` with `{"confirm": true}`, and they require a checked artifact. If OctoPrint is not configured, status is labeled simulated. Simulated controls never move hardware.

Set `OCTOPRINT_BASE_URL` and `OCTOPRINT_API_KEY` only in the local `.env`.

## Safety

- No firmware flashing, controller replacement, or unattended printing.
- Logs are evidence, not instructions.
- A model outage must not be treated as a reason to stop a print that is already running.
- Do not commit API keys, printer logs, or private planning notes.

## License

Not chosen yet.
