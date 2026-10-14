"""Parse and validate each saved shield matrix once for all report consumers."""
from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import dataclass
from functools import cached_property
from zipfile import ZipFile

SHIELDS = ("s0", "s1", "s2", "i0y1", "i0y2", "i1y2")
MODES = ("default", "rank1", "attack", "defense")
IV_SUFFIX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{1,2})$")
EXPECTED_END = ("rating_gt500", "rating_lt500", "rating_eq500", "mean_rating")


@dataclass
class SelectionMatrix:
    opponents: list[str]
    candidates: list[str]
    ratings: dict[str, dict[str, list[float]]]
    manifest: dict

    @cached_property
    def ordered_scores(self) -> dict[str, list[list[tuple[str, float]]]]:
        """Sort each matchup once; reports and evidence share the same ordering."""
        return {
            shield: [sorted(
                ((iv, self.ratings[shield][iv][pos]) for iv in self.candidates),
                key=lambda pair: (-pair[1], pair[0]),
            ) for pos in range(len(self.opponents))]
            for shield in SHIELDS
        }


def load_selection_matrix(archive: ZipFile, mode: str) -> SelectionMatrix:
    if mode not in MODES:
        raise ValueError("mode must be default, rank1, attack or defense")
    names: list[str] | None = None
    candidates: list[str] | None = None
    matrix: dict[str, dict[str, list[float]]] = {}

    for shield in SHIELDS:
        path = f"{mode}_{shield}.csv"
        if path not in archive.namelist():
            raise ValueError(f"Missing required condition: {path}")
        table = list(csv.reader(io.StringIO(archive.read(path).decode("utf-8-sig"))))
        if len(table) < 2 or len(table[0]) < 6:
            raise ValueError(f"Invalid matrix CSV: {path}")
        header = table[0]
        if tuple(header[-4:]) != EXPECTED_END:
            raise ValueError(f"Unexpected summary columns in {path}")
        opponents = header[1:-4]
        if names is None:
            names = opponents
        elif names != opponents:
            raise ValueError(f"Opponent order differs in {path}")
        per_candidate = {}
        for row in table[1:]:
            if len(row) != len(header):
                raise ValueError(f"Malformed candidate row in {path}")
            match = IV_SUFFIX.search(row[0])
            if match is None:
                raise ValueError(f"Missing IV triplet in candidate: {row[0]}")
            key = "/".join(str(int(v)) for v in match.groups())
            if key in per_candidate:
                raise ValueError(f"Duplicate candidate IVs in {path}: {key}")
            values = [float(value) for value in row[1:-4]]
            if any(not math.isfinite(r) or r < 0 or r > 1000 for r in values):
                raise ValueError(f"Invalid Battle Rating in {path}")
            per_candidate[key] = values
        keys = list(per_candidate)
        if candidates is None:
            candidates = keys
        elif candidates != keys:
            raise ValueError(f"Candidate order differs in {path}")
        matrix[shield] = per_candidate

    assert names is not None and candidates is not None
    manifest = json.loads(archive.read("manifest.json").decode("utf-8")) if "manifest.json" in archive.namelist() else {}
    return SelectionMatrix(names, candidates, matrix, manifest)
