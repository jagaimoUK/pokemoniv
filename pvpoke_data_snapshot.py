"""Approved upstream data, separate from the locally modified battle engine."""
import hashlib
import tempfile
from pathlib import Path

COMMIT = '797820327642f49deb8e9706492090ccac680bc7'
FILES = {
    'gamemaster.json': ('data/gamemaster.json', 'd8e690f82c24d4037e3bb15ff664b63ff7a11005e8255e40c903e1b01712009b'),
    'Pokemon.js': ('js/pokemon/Pokemon.js', 'a3646035edfe30e8136e8121ed3981aec2bcf094dca582354234b79eca34321e'),
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
