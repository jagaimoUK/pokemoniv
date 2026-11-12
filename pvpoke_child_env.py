"""Minimal environment for untrusted browser and numerical Node subprocesses."""
import os


def child_environment(extra=None):
    allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(extra or {})
    return env

# Deliberately narrow list of settings used by the legacy Python matrix
# workflow and its direct Node worker. Never forward the gateway root key,
# OAuth credentials, cloud backup credentials or arbitrary PVP_* variables.
_IV_WORKER_SETTINGS = (
    'PVP_ENGINE', 'PVP_ALLOW_BROWSER', 'PVP_PVPOKE_SOURCE',
    'PVP_CAND_CHUNK', 'PVP_OPP_CHUNK', 'PVP_MATCHUP_CACHE',
    'PVP_CACHE_EPOCH', 'PVP_BROWSER_CACHE_EPOCH',
    'PVP_RESULT_CACHE', 'PVP_RESULT_CACHE_TTL_SECONDS',
    'PVP_RESULT_CACHE_MAX_MB', 'PVP_RESULT_CACHE_MAX_ENTRIES',
    'PVP_FORCE_RECALCULATE',
    'PVP_ARCHIVE_DIR', 'RAILWAY_VOLUME_MOUNT_PATH',
)


def iv_worker_environment(*, force=False):
    """Pass only required runtime settings to IV calculation subprocesses.

    Public gateway, S3 and OAuth secrets belong to the parent process only.
    The archive mount and cache/engine knobs are retained for compatibility.
    """
    if type(force) is not bool:
        raise TypeError('force must be a boolean')
    extra = {name: os.environ[name] for name in _IV_WORKER_SETTINGS
             if name in os.environ}
    if force:
        extra['PVP_FORCE_RECALCULATE'] = '1'
    return child_environment(extra)
