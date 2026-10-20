"""Real pinned PvPoke JavaScript engine integration smoke for Minior (online GameMaster).

Run in CI only: downloads official PvPoke data, then validates the actual
Node Matrix protocol for 3 energy policies with a live species/moveset.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pvpoke_batch_v2 as engine
from pvpoke_direct_backend import DirectMatrixClient

def main():
    with tempfile.TemporaryDirectory(prefix="minior_smoke_") as directory:
        folder = Path(directory)
        old_data = engine.DATA
        try:
            engine.DATA = folder / "game_data"
            gm, cpms, species = engine.game_data()
        finally:
            engine.DATA = old_data
        assert "minior_meteor" in species and "minior_core" in species, (
            "PvPoke live GameMaster lacks Minior's two required forms")
        meteor = species["minior_meteor"]
        other = species["quagsire"]
        assert len(meteor["chargedMoves"]) >= 2
        assert len(other["chargedMoves"]) >= 2
        def prepared(species_id, info, atk, defense, hp):
            row = {
                "species": species_id, "fast": info["fastMoves"][0],
                "charged1": info["chargedMoves"][0],
                "charged2": info["chargedMoves"][1],
                "atk": atk, "def": defense, "hp": hp,
            }
            return engine.optimize([row], species, cpms, "smoke.csv")[0]

        own = [prepared("minior_meteor",meteor,0,14,15)]
        opp = [prepared("quagsire",other,0,14,15)]
        with_client = DirectMatrixClient(gamemaster=folder / "game_data" / "gamemaster.json",
                                         log_dir=folder, timeout_seconds=60)
        try:
            for shields in ((0,0),(1,1),(0,1)):
                matrix = with_client.simulate(own,opp,shields)
                evidence = with_client.last_minior_data
                assert evidence is not None and len(evidence)==1
                assert len(matrix)==2 and len(matrix[1])==6
                assert evidence[0]["policies"][0] in ("instant","hold","adaptive")
                print(json.dumps({"shields":shields, "rating":matrix[1][1],
                  "selected":evidence[0]["policies"][0],
                  "strategy_ratings":evidence[0]["strategy_ratings"],
                  "game_master_timestamp":gm.get("timestamp")},ensure_ascii=False))
        finally:
            with_client.close()
    print("REAL MINIOR NODE MATRIX SMOKE PASS")


if __name__ == "__main__":
    main()
