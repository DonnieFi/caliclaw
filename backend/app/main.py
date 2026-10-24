"""FastAPI entrypoint for CaliClaw."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from .db import init_db
from .poc_api import router as poc_router

DB_PATH = os.environ.get("CALICLAW_DB") or os.environ.get("BEAMBENCH_DB") or "caliclaw.db"

app = FastAPI(title="CaliClaw", version="0.1.0")
app.include_router(poc_router)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "db": str(Path(DB_PATH).resolve())})


@app.on_event("startup")
def startup() -> None:
    init_db(DB_PATH)


WEB_DIR = Path(__file__).resolve().parents[2] / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
