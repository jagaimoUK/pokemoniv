FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS node-runtime
FROM python:3.12-slim-trixie@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PVP_ENGINE=direct PVP_ALLOW_BROWSER=0
RUN apt-get update && apt-get install -y --no-install-recommends nginx libstdc++6 ca-certificates gosu && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 appuser
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/LICENSE /app/vendor/node/LICENSE
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY *.py /app/
# Fetch and verify the approved data while building, not on each container start.
RUN python -c "from pathlib import Path; from pvpoke_data_snapshot import install_snapshot, SEED; from pvpoke_batch_v2 import urlget; install_snapshot(SEED, urlget)"
COPY pvpoke_node_matrix.js /app/pvpoke_node_matrix.js
COPY pvpoke_minior_strategy.js /app/pvpoke_minior_strategy.js
COPY pvpoke_battle_policy.js /app/pvpoke_battle_policy.js
RUN node -e "if(require('./pvpoke_battle_policy.js').SCHEMA !== 'strategy-detail-v1') process.exit(1)"
COPY flashcards.html flashcards_core.js flashcards_ui.js /app/
COPY pvpoke_browser_migration.js /app/
COPY pvpoke_party_strategy_ui.js pvpoke_party_input.js /app/
COPY data/flashcard_catalog.json /app/data/flashcard_catalog.json
# Node loads this module at startup for *every* matrix, not just Minior.
# Validate the deployed image here so missing modules cannot reach production.
RUN node -e "const s=require('./pvpoke_minior_strategy.js'); if (s.POLICIES.join(',') !== 'instant,hold,adaptive') process.exit(1)"
COPY vendor/pvpoke /app/vendor/pvpoke
COPY pvpoke_meta_opponents.csv /app/pvpoke_meta_opponents.csv
# Low-score CP1500 snapshot is a build-time immutable asset, not the Railway /data volume.
COPY data/cp1500_role_scores_20261015.json /app/data/cp1500_role_scores_20261015.json
COPY data/pokemon_species_evolutions_20261019.json /app/data/pokemon_species_evolutions_20261019.json
COPY data/pvpoke_meta_presets.json /app/data/pvpoke_meta_presets.json
RUN python -c "from pvpoke_flashcards import page; assert '/*CORE*/' not in page()"
RUN python -c "from pvpoke_meta_presets import bundled; assert any(p['id'] == 'pvpoke:fantasy' for p in bundled()['items'])"
# Fail deployment at build time instead of returning 500 from /app-api/low-score.
RUN python -c "from pvpoke_score_search import load_snapshot, evolution_descendants; assert len(load_snapshot()[1]) == 1153; assert len(evolution_descendants()) == 1025"
COPY nginx.conf.template /app/nginx.conf.template
COPY THIRD_PARTY_NOTICES.md /app/THIRD_PARTY_NOTICES.md
COPY start.sh /app/start.sh
COPY volume_bootstrap.sh /app/volume_bootstrap.sh
COPY tests/smoke_minior_direct.py /tmp/pvpoke-build-smoke.py
RUN chmod +x /app/start.sh /app/volume_bootstrap.sh && chown -R appuser:appuser /app
# The real build validates proxy configuration with the runtime's unprivileged UID.
USER appuser
RUN PORT=8787 python /app/pvpoke_proxy_config.py \
    && mkdir -p /tmp/pokemoniv-nginx/body /tmp/pokemoniv-nginx/proxy /tmp/pokemoniv-nginx/fastcgi /tmp/pokemoniv-nginx/uwsgi /tmp/pokemoniv-nginx/scgi \
    && nginx -t -e stderr -c /tmp/pokemoniv-nginx.conf \
    && PYTHONPATH=/app python /tmp/pvpoke-build-smoke.py \
    && python -m pip inspect > /app/runtime-python-packages.json \
    && dpkg-query -W > /app/runtime-os-packages.txt
# Initialize the root-owned Railway mount once, then drop to appuser.
USER root
CMD ["/app/volume_bootstrap.sh"]

# Browser binaries are isolated to a CI-only target, never the default deployment.
FROM runtime AS browser-check
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/chromium /usr/local/bin/chromium-browser
FROM runtime AS production
