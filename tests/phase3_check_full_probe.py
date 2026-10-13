"""Compare direct Node TeamRanker against all recorded production PvPoke Matrix rows."""
import json
import sys
from pathlib import Path
result=[json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
baseline=json.loads((Path(__file__).resolve().parent/"phase3_full_production_baseline.json").read_text(encoding="utf-8"))
names=["s0","s1","s2","i0y1","i0y2","i1y2"]
if len(result)!=6:
    raise SystemExit(f"Expected six complete Node results, got {len(result)}")
mismatch=[]
correct=0
for shield,output in zip(names,result):
    if not output.get("ok"):
        mismatch.append((shield,"engine failed",output.get("error")))
        continue
    actual=output["result"]["candidates"]
    expected=baseline["conditions"][shield]
    if len(actual)!=len(expected):
        mismatch.append((shield,"candidate count",len(actual),len(expected)))
        continue
    for i,(row,ref) in enumerate(zip(actual,expected)):
        if row["label"]!=ref["candidate"]:
            mismatch.append((shield,i,"candidate label",row["label"],ref["candidate"]))
        if row["opponents"]!=ref["opponents"]:
            mismatch.append((shield,i,"opponent labels",
                             list(zip(row["opponents"],ref["opponents"]))[:5]))
        if len(row["ratings"])!=len(ref["ratings"]):
            mismatch.append((shield,i,"ratings length",len(row["ratings"]),len(ref["ratings"])))
        else:
            for j,(a,b) in enumerate(zip(row["ratings"],ref["ratings"])):
                if a!=b:
                    mismatch.append((shield,i,j,a,b,ref["opponents"][j]))
                else:
                    correct+=1
    print(f"{shield}: {len(actual)} candidates x {len(expected[0]['ratings'])} opponents",flush=True)
print(f"Matching ratings: {correct}/1566, mismatches={len(mismatch)}",flush=True)
for item in mismatch[:35]:print("MISMATCH:",repr(item),flush=True)
if mismatch:raise SystemExit("Full browser-free parity NOT verified")
print("ALL 1,566 ratings and labels exactly matched production!",flush=True)
