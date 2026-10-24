"""Fit notes remember a measurement without replacing the part."""
from pathlib import Path

from backend.app.db import init_db
from backend.app.fit import fit_memory_text, list_fit, project_snapshot, record_fit
from backend.app.repository import create_project


def test_fit_note_is_kept_and_named_features_stay_protected(tmp_path: Path):
    db = tmp_path / "fit.db"
    init_db(db)
    project = create_project(db, "Workshop")
    with_empty = None
    try:
        record_fit(db, project.id, note="   ")
    except ValueError as exc:
        with_empty = str(exc)
    assert with_empty == "a fit note needs what you measured"

    saved = record_fit(
        db,
        project.id,
        note="USB opening is 2 mm too far right",
        measured={"usb_x_mm": 18},
        keep=["mounting hole spacing", ""],
    )
    assert saved["keep"] == ["mounting hole spacing"]
    again = list_fit(db, project.id)
    assert len(again) == 1
    assert again[0]["measured"]["usb_x_mm"] == 18

    view = project_snapshot(db, project.id, project.name)
    assert view["keep"] == ["mounting hole spacing"]
    memory = fit_memory_text(db, project.id)
    assert "USB opening is 2 mm too far right" in memory
    assert "mounting hole spacing" in memory
    assert "usb_x_mm=18" in memory
