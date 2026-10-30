"""Anonymous local HTML gateway for CSP browser regression; fake key only."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['PVP_API_KEY'] = 'browser-fixture-' + 'x' * 40
os.environ.pop('VISUAL_BACKUP_S3_BUCKET', None)
import pvpoke_mcp_remote as remote
from pvpoke_http_security import BoundedHTTPServer

with BoundedHTTPServer(('127.0.0.1', 0), remote.Handler) as server:
    print(server.server_port, flush=True)
    server.serve_forever()
