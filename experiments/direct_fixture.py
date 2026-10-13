"""Generate a parity fixture using exactly the Python CP preparation rules."""
import json
from pathlib import Path
import pvpoke_batch_v2 as engine
gm, cpms, species = engine.game_data()
def prepared(species_id, fast, charged1, charged2, atk, defense, hp):
    row = dict(species=species_id, fast=fast, charged1=charged1,
               charged2=charged2, atk=atk, **{"def": defense}, hp=hp)
    return engine.optimize([row],species,cpms,"fixture")[0]
root=Path(__file__).resolve().parent
names={"gameMasterJs":"GameMaster.js","battleJs":"Battle.js","pokemonJs":"Pokemon.js"}
payload=dict(
  sources={key:(root/name).read_text(encoding="utf-8") for key,name in names.items()},
  gameMaster=gm,
  candidate=prepared("quagsire","MUD_SHOT","AQUA_TAIL","STONE_EDGE",2,12,3),
  opponent=prepared("clodsire","POISON_STING","STONE_EDGE","EARTHQUAKE",4,14,10),
  shields=[1,1],
  expectedRating=636
)
(root/"fixture.json").write_text(json.dumps(payload),encoding="utf-8")
print(json.dumps({"candidate":payload["candidate"],"opponent":payload["opponent"],"expected":636},ensure_ascii=False))
