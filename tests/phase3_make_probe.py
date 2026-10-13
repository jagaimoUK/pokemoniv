"""Create a reproducible direct-engine parity probe from pinned PvPoke source."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pvpoke_batch_v2 as engine

src=Path(sys.argv[1]).resolve()
out=Path(sys.argv[2]).resolve()
data_file=src/"src/data/gamemaster.json"
gm=json.loads(data_file.read_text(encoding="utf-8"))
pokemon_js=(src/"src/js/pokemon/Pokemon.js").read_text(encoding="utf-8")
cpms=[float(x.strip()) for x in re.search(
    r"\bvar\s+cpms\s*=\s*\[([^\]]+)\]",pokemon_js,re.S).group(1).split(",") if x.strip()]
species={p["speciesId"]:p for p in gm["pokemon"]}
candidate=engine.optimize([dict(species="quagsire",fast="MUD_SHOT",
                 charged1="AQUA_TAIL",charged2="STONE_EDGE",
                 atk=1,**{"def":11},hp=8)],species,cpms,"candidate")[0]
opponents=engine.optimize([
 dict(species="altaria",fast="DRAGON_BREATH",charged1="SKY_ATTACK",
      charged2="FLAMETHROWER",atk=4,**{"def":12},hp=13),
 dict(species="clodsire",fast="POISON_STING",charged1="STONE_EDGE",
      charged2="EARTHQUAKE",atk=4,**{"def":14},hp=10),
 dict(species="corsola_galarian",fast="ASTONISH",charged1="NIGHT_SHADE",
      charged2="POWER_GEM",atk=4,**{"def":15},hp=14)
],species,cpms,"opponent")
shields=[(0,0),(1,1),(2,2),(0,1),(0,2),(1,2)]
with out.open("w",encoding="utf-8") as fp:
    for pair in shields:
        fp.write(json.dumps({"gamemaster_path":str(data_file),
            "candidates":[candidate],"opponents":opponents,
            "shields":pair})+"\n")
print("Prepared:",candidate["species"],candidate["level"],candidate["cp"],
      [(o["species"],o["level"],o["cp"]) for o in opponents])
