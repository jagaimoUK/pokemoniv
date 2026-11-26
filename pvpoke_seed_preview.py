"""Seed synthetic individual for Cloud Run isolated preview testing."""
import os
from pathlib import Path
from pvpoke_archive import archive_dir
from pvpoke_battle_store import BattleStore
from pvpoke_ownership import Ownership


def seed():
    if os.environ.get('RAILWAY_VOLUME_MOUNT_PATH'):
        raise RuntimeError('Refusing to seed preview data when RAILWAY_VOLUME_MOUNT_PATH is set')
    data_dir = archive_dir(Path('.'))
    data_dir.mkdir(parents=True, exist_ok=True)
    store = BattleStore.from_volume()
    inv = Ownership(store, species_ids={'quagsire'})
    obs = {
        'species_id': 'quagsire',
        'current_cp': 1498,
        'ivs': {'attack': 0, 'defense': 11, 'hp': 12}
    }
    try:
        inv.register('smoke-known-1', obs)
        inv.confirm('conf-1', 'smoke-known-1', expected_revision=0, state='confirmed_owned')
        inv.register('smoke-unconfirmed-2', obs)
        print('Cloud Run Preview: synthetic Quagsire seeded into', store.path, flush=True)
    except Exception as exc:
        print('Cloud Run Preview seed note:', type(exc).__name__, exc, flush=True)


if __name__ == '__main__':
    seed()
