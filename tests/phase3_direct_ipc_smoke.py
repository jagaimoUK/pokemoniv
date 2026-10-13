"""Run the actual Python->Node IPC backend against three recorded real PvPoke IVs."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pvpoke_direct_backend import DirectMatrixClient

req=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()[1])
source=Path(sys.argv[2])
with_client=DirectMatrixClient(
    gamemaster=Path(req["gamemaster_path"]),
    log_dir=Path("/tmp"),
    source=source)
try:
    actual=with_client.simulate(req["candidates"],req["opponents"],tuple(req["shields"]))
finally:
    with_client.close()
baseline=json.loads((Path(__file__).parent/"phase3_full_production_baseline.json").read_text())
expected=baseline["conditions"]["s1"]
assert len(actual)==4, len(actual)
assert len(actual[0])==92, len(actual[0])  # label + 87 opponent names + four stats
for i,ref in enumerate(expected):
    row=actual[i+1]
    assert row[0]==ref["candidate"], (i,row[0],ref["candidate"])
    assert row[1:88]==ref["ratings"], (i,[(a,b) for a,b in zip(row[1:88],ref["ratings"]) if a!=b][:5])
    assert actual[0][1:88]==ref["opponents"], i
print("Python-to-Node direct engine: 261/261 ratings and labels matched browser Matrix.")
