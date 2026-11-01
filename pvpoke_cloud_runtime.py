"""Fail closed until durable stores and workers have passed migration gates."""
import os
from pathlib import Path


def check(environ=None):
    env = os.environ if environ is None else environ
    if not env.get('K_SERVICE'):
        return  # Existing Railway/local operation is unchanged.
    if env.get('PVP_CLOUD_MODE') != 'validation':
        raise ValueError('Cloud Run production is blocked: durable state, jobs and data reconciliation are not verified')
    archive = Path(env.get('PVP_ARCHIVE_DIR', ''))
    if (not archive.is_absolute() or archive == Path('/tmp')
            or Path('/tmp') not in archive.parents or '..' in archive.parts):
        raise ValueError('Validation requires a disposable PVP_ARCHIVE_DIR strictly below /tmp')
    if env.get('RAILWAY_VOLUME_MOUNT_PATH') or env.get('PVP_AUTH_DB'):
        raise ValueError('Validation must not attach production data or authentication stores')
    if any(env.get(key) for key in env if key.startswith('VISUAL_BACKUP_S3_')):
        raise ValueError('Validation must not access the production visual backup bucket')


if __name__ == '__main__':
    try:
        check()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
