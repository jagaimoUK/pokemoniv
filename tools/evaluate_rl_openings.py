"""Compare switches and charged moves on predeclared synthetic matchups."""
from __future__ import annotations

import argparse
import json

from tools.evaluate_rl_branches import PRIMEAPE, compare_cases
from tools.evaluate_rl_mc import fixed_public_action
from tools.run_rl_mc import fixture_teams

SEED_WINDOWS = (600012, 601012)
SEEDS_PER_WINDOW = 2
LAST_OPENING_TURN = 8

# The same six are available in each own configuration. Swap the lead and
# slot-1 switch target independently, with Wigglytuff always in slot 2.
OWN_SELECTIONS = (
    ("azumarill", "fearow", "2,3,5|2"),
    ("azumarill", "primeape", "0,2,5|2"),
    ("skarmory", "fearow", "3,4,5|4"),
    ("skarmory", "primeape", "0,4,5|4"),
)

# (Primeape pool slot, fixed selected trio, two alternative leads). Vary the
# visible lead within each pool without also changing its selected members.
OPPONENT_POOLS = ((3, (1, 3, 5), (1, 3)),
                  (1, (1, 4, 5), (4, 5)))


def opening_switch(view):
    """Search only turns 2–8 with the original two Pokémon still active."""
    own = view["own"]
    revealed = view["opponent"]["revealed"]
    return (2 <= view["turn"] <= LAST_OPENING_TURN and own["active_slot"] == 0 and
            len(revealed) == 1 and not revealed[0]["fainted"] and
            own["team"][1]["hp"] == own["team"][1]["max_hp"])


def own_lead_active(view):
    return view["own"]["active_slot"] == 0


def bank_charge_energy(view):
    """Keep the lead in and bank energy before the charge-choice fork."""
    if view["phase"] == "turn" and own_lead_active(view):
        if "fast" in view["legal_actions"]:
            return "fast"
        if "wait" in view["legal_actions"]:
            return "wait"
    return fixed_public_action(view)


def compare_openings(*, pair, window):
    if pair not in ("switch", "charge") or type(window) is not int or window not in SEED_WINDOWS:
        raise ValueError("Select a predeclared pair and seed window")
    own, _, opponent_fixture = fixture_teams()
    own[0] = {**own[0], **PRIMEAPE}
    reports = []
    for slot, trio, leads in OPPONENT_POOLS:
        opponent = opponent_fixture.copy()
        opponent[slot] = {**opponent[slot], **PRIMEAPE}
        public = [{"species": row["species"], "roster_clause_id": row["roster_clause_id"]}
                  for row in opponent]
        for lead in leads:
            cases = [(seed, trio, lead) for seed in range(window, window + SEEDS_PER_WINDOW)]
            for own_lead, target, selection in OWN_SELECTIONS:
                if pair == "charge" and target != "fearow":
                    continue  # Keep a common bench for the charge-choice study.
                stats = compare_cases(
                    pair=pair, teams=(own, public, opponent), cases=cases, selection=selection,
                    frontier_filter=opening_switch if pair == "switch" else own_lead_active,
                    prefix_policy=bank_charge_energy if pair == "charge" else None,
                )
                reports.append({"own_lead": own_lead, "slot_1": target,
                                "opponent_lead": opponent[lead]["species"], **stats})
    return {"pair": pair, "seed_window": window, "seeds_per_matchup": SEEDS_PER_WINDOW,
            "matchups": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", choices=("switch", "charge"), required=True)
    parser.add_argument("--window", type=int, choices=SEED_WINDOWS, required=True)
    args = parser.parse_args()
    print(json.dumps(compare_openings(pair=args.pair, window=args.window), sort_keys=True))


if __name__ == "__main__":
    main()
