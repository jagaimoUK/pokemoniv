"""Approved upstream data, separate from the locally modified battle engine."""
import hashlib
import tempfile
from pathlib import Path

COMMIT = '6477226670913974993c1f7c936331d55cd7d893'
FILES = {
    'gamemaster.json': ('data/gamemaster.json', '8fe95164126c6c108a0b02a68998ed68a46f597226466870e767be472f1c76e4'),
    'Pokemon.js': ('js/pokemon/Pokemon.js', '10893308f8e8b408d396d19e541d7482c9657dd9c07fd6c8c9bf8f783669c47d'),
}
SEED = Path(__file__).with_name('data') / 'pvpoke_runtime'


def install_snapshot(target, fetch, refresh=False, seed=None):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    seed = Path(seed) if seed is not None else SEED
    for name, (source, expected) in FILES.items():
        path = target / name
        if not refresh and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        bundled = seed / name
        data = bundled.read_bytes() if bundled.is_file() else None
        if data is None or hashlib.sha256(data).hexdigest() != expected:
            data = fetch(f'https://raw.githubusercontent.com/pvpoke/pvpoke/{COMMIT}/src/{source}')
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'Approved PvPoke snapshot hash mismatch: {name}')
        # Concurrent readers never see partial data or share a temporary filename.
        with tempfile.NamedTemporaryFile(dir=target, prefix=name + '.', suffix='.tmp', delete=False) as tmp:
            temp = Path(tmp.name)
            try:
                tmp.write(data)
                tmp.flush()
            except Exception:
                temp.unlink(missing_ok=True)
                raise
        try:
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
