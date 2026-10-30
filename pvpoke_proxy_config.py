"""Render only the validated listening port; leave Nginx variables literal."""
import os
from pathlib import Path


def render(port):
    port = int(port)
    if not 1024 <= port <= 65535 or port in (8765, 8788):
        raise ValueError('PORT must be 1024..65535, excluding private engine ports')
    return Path(__file__).with_name('nginx.conf.template').read_text().replace('__PORT__', str(port))


if __name__ == '__main__':
    Path('/tmp/pokemoniv-nginx.conf').write_text(render(os.environ.get('PORT', '8787')))
