"""Role predicates and partial ordering for one declared scenario set."""
import re

from pvpoke_observed_observation import integer

OUTCOME_ORDER = ("opponent_ko_win", "simultaneous_ko", "self_ko_win")
KNOWN = (*OUTCOME_ORDER, "timeout")
LIMITS = {"hp": 10000, "energy": 100, "shields": 2}
VERSION = "observed-terminal-roles-v1"


def normalize_roles(value):
    if type(value) is not list or not 1 <= len(value) <= 8:
        raise ValueError("Expected 1–8 observed roles")
    roles = []
    ids = set()
    for role in value:
        if type(role) is not dict or set(role) != {"id", "priority", "outcomes", "minimum"}:
            raise ValueError("Invalid observed role")
        name, outcomes, minima = role["id"], role["outcomes"], role["minimum"]
        if (type(name) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", name)
                or name in ids or not integer(role["priority"], 0, 1000)
                or type(outcomes) is not list or not 1 <= len(outcomes) <= len(KNOWN)
                or any(outcome not in KNOWN for outcome in outcomes)
                or len(set(outcomes)) != len(outcomes)
                or type(minima) is not dict or not minima.keys() <= LIMITS.keys()
                or any(not integer(n, 0, LIMITS[key]) for key, n in minima.items())):
            raise ValueError("Invalid observed role condition")
        ids.add(name)
        roles.append({**role, "outcomes": sorted(outcomes), "minimum": dict(minima)})
    return sorted(roles, key=lambda role: (-role["priority"], role["id"]))


def evaluate_roles(roles, cells, count):
    known = [cell for cell in cells if cell["outcome"] in KNOWN]
    unknown = count - len(known)
    outcomes = {cell["outcome"] for cell in known}
    # A simulated horizon is a distinct result with no inferred KO ordering.
    worst = (next(iter(outcomes)) if len(outcomes) == 1 else
             min(outcomes, key=OUTCOME_ORDER.index) if outcomes and "timeout" not in outcomes else None)
    resources = [cell["terminal"][0] for cell in known]
    floor = dict(zip(LIMITS, map(min, zip(*resources)))) if resources else None
    rows = []
    for role in roles:
        matches = [None if cell["outcome"] not in KNOWN else
                   cell["outcome"] in role["outcomes"] and all(
                       dict(zip(LIMITS, cell["terminal"][0]))[key] >= n
                       for key, n in role["minimum"].items()) for cell in cells]
        passed = matches.count(True)
        failed = len(known) - passed
        rows.append({"id": role["id"], "priority": role["priority"], "passed": passed,
                     "failed": failed, "unknown": unknown,
                     "meets": False if failed else None if unknown else True,
                     "worst_outcome": None if unknown else worst,
                     "scenario_meets": matches, "sample_min": worst, "resource_floor": None if unknown else floor})
    return rows


def compare(left, right):
    """Compare two policies for the same build, roles and scenario manifest."""
    a, b = left["roles"], right["roles"]
    if [(r["id"], r["priority"]) for r in a] != [(r["id"], r["priority"]) for r in b]:
        raise ValueError("Policies have different role definitions")
    if any(r["unknown"] for r in (*a, *b)):
        return "incomparable"
    for priority in sorted({r["priority"] for r in a}, reverse=True):
        x, y = ({r["id"] for r in rows if r["priority"] == priority and r["meets"]}
                for rows in (a, b))
        if x != y:
            return "better" if x > y else "worse" if x < y else "incomparable"
    x, y = a[0]["worst_outcome"], b[0]["worst_outcome"]
    if x != y:
        if x not in OUTCOME_ORDER or y not in OUTCOME_ORDER:
            return "incomparable"
        return "better" if OUTCOME_ORDER.index(x) > OUTCOME_ORDER.index(y) else "worse"
    if x is None and left["outcomes"] != right["outcomes"]:
        return "incomparable"
    x, y = left["resources"], right["resources"]
    if x == y:
        return "equal"
    pairs = list(zip((n for row in x for n in row), (n for row in y for n in row), strict=True))
    return ("better" if all(a >= b for a, b in pairs) else
            "worse" if all(a <= b for a, b in pairs) else "incomparable")
