"""Minimal environment for untrusted browser and numerical Node subprocesses."""
import os


def child_environment(extra=None):
    allowed = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'SYSTEMROOT')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(extra or {})
    return env
