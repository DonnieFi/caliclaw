#!/usr/bin/env python3
"""Clearly labeled deterministic simulated print (no hardware)."""
from __future__ import annotations

import time

from backend.app.collector import SimulatedPrinterState

state = SimulatedPrinterState(temperature=200.0, bed_temperature=60.0)
print("SIMULATION: no hardware is operated.")
state.start()
for i in range(10):
    state.advance(0.1)
    print(f"progress={state.progress:.1f} state={state.state} temp={state.temperature} bed={state.bed_temperature}")
    time.sleep(0.2)
print("simulation complete:", state.to_dict())
