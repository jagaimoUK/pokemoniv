"""Build full 3x87x6 matrix inputs from the pinned PvPoke GameMaster and meta."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pvpoke_batch_v2 as engine
import pvpoke_24_workflow as workflow

root=Path(sys.argv[1]).resolve()
dest=Path(sys.argv[2]).resolve()
gm_path=root/"src/data/gamemaster.json"
gm=json.loads(gm_path.read_text(encoding="utf-8"))
js=(root/"src/js/pokemon/Pokemon.js").read_text(encoding="utf-8")
cpms=[float(part.strip()) for part in re.search(
    r"\bvar\s+cpms\s*=\s*\[([^\]]+)\]",js,re.S).group(1).split(",") if part.strip()]
species={p["speciesId"]:p for p in gm["pokemon"]}
meta,source_errors=workflow.load_meta(Path(__file__).resolve().parents[1]/"pvpoke_meta_opponents.csv",species)
rows,report,mode_errors,counts=workflow.generate_rows(meta,species,cpms,full_modes=("default",))
if source_errors or mode_errors or len(meta)!=87 or len(rows)!=87:
    raise ValueError(f"Meta source parity expected 87 valid rows, got {len(meta)}/{len(rows)} with errors {source_errors}/{mode_errors}")
own_rows=[dict(species="quagsire",fast="MUD_SHOT",charged1="AQUA_TAIL",
               charged2="STONE_EDGE",atk=atk,**{"def":defense},hp=hp)
          for atk,defense,hp in [(1,11,8),(4,15,15),(6,4,12)]]
own=engine.optimize(own_rows,species,cpms,"candidates.csv")
opponents=engine.optimize(rows,species,cpms,"opponents.csv")
with dest.open("w",encoding="utf-8") as fp:
    for shields in ((0,0),(1,1),(2,2),(0,1),(0,2),(1,2)):
        fp.write(json.dumps({"gamemaster_path":str(gm_path),"candidates":own,
                             "opponents":opponents,"shields":list(shields)},
                            ensure_ascii=False)+"\n")
print(f"Prepared {len(own)} own IVs x {len(opponents)} opponent modes x 6 shields", flush=True)
