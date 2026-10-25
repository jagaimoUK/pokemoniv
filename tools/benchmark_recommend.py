"""Seeded recommendation timings and exact parity with a prior module.

python tools/benchmark_recommend.py --baseline /tmp/old_selection.py
Synthetic ratings measure analysis only, not battle or network time.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pvpoke_app_selection import recommend
from pvpoke_selection_matrix import MODES, SHIELDS, SelectionMatrix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--samples', type=int, default=5)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    previous = None
    if args.baseline:
        spec = importlib.util.spec_from_file_location('selection_baseline', args.baseline)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        previous = module.recommend
    rng = random.Random(669)
    for count, modes in [(3, 1), (40, 1), (150, 1), (150, 4), (300, 1)]:
        ivs = [f'{i//256}/{i//16%16}/{i%16}' for i in range(count)]
        matrices = {mode: SelectionMatrix([f'Opponent {i}' for i in range(87)], ivs,
                    {shield: {iv: [rng.randint(300,700) for _ in range(87)] for iv in ivs}
                     for shield in SHIELDS}, {}) for mode in MODES[:modes]}
        inputs = (matrices, {'species': 'quagsire'}, 'Quagsire', ['Opponent 0'])
        if previous:
            assert previous(*inputs) == recommend(*inputs), 'Recommendation output changed'
        row = {'candidates': count, 'modes': modes}
        for name, fn in [('before_ms', previous), ('after_ms', recommend)]:
            if fn is None:
                continue
            times = []
            for _ in range(args.samples):
                start = time.perf_counter()
                fn(*inputs)
                times.append((time.perf_counter() - start) * 1000)
            row[name] = round(statistics.median(times), 2)
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
