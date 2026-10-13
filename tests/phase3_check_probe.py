"""The recorded expected ratings are from the existing production Matrix on 2026-10-13."""
import json
import sys
from pathlib import Path
lines=[json.loads(l) for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]
expected=[
 [394,672,410], # 0/0
 [416,645,512], # 1/1
 [355,756,474], # 2/2
 [119,435,305], # 0/1
 [50,283,201], # 0/2
 [141,512,406], # 1/2
]
if len(lines)!=6:
    raise SystemExit(f"expected 6 responses, got {len(lines)}: {lines}")
wrong=[]
for i,(row,known) in enumerate(zip(lines,expected)):
    if not row.get("ok"):
        wrong.append((i,row.get("error")))
        continue
    actual=row["result"]["candidates"][0]["ratings"]
    if actual!=known:
        wrong.append((i,known,actual))
    print(f"Shield {i}: expected={known}, Node={actual}")
if wrong:
    raise SystemExit("PARITY NOT VERIFIED: "+repr(wrong))
print("ALL 18 PvPoke matrix ratings matched exactly.")
