FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PVP_ENGINE=direct
RUN apt-get update && apt-get install -y --no-install-recommends chromium nodejs fonts-noto-core ca-certificates gosu && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/chromium /usr/local/bin/chromium-browser \
    && useradd -m -u 10001 appuser
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py /app/
COPY pvpoke_node_matrix.js /app/pvpoke_node_matrix.js
COPY pvpoke_minior_strategy.js /app/pvpoke_minior_strategy.js
# Node loads this module at startup for *every* matrix, not just Minior.
# Validate the deployed image here so missing modules cannot reach production.
RUN node -e "const s=require('./pvpoke_minior_strategy.js'); if (s.POLICIES.join(',') !== 'instant,hold,adaptive') process.exit(1)"
COPY vendor/pvpoke /app/vendor/pvpoke
COPY pvpoke_meta_opponents.csv /app/pvpoke_meta_opponents.csv
# Low-score CP1500 snapshot is a build-time immutable asset, not the Railway /data volume.
COPY data/cp1500_role_scores_20261015.json /app/data/cp1500_role_scores_20261015.json
COPY data/pokemon_species_evolutions_20261019.json /app/data/pokemon_species_evolutions_20261019.json
COPY data/pvpoke_meta_presets.json /app/data/pvpoke_meta_presets.json
RUN python -c "from pvpoke_meta_presets import bundled; assert any(p['id'] == 'pvpoke:fantasy' for p in bundled()['items'])"
# Fail deployment at build time instead of returning 500 from /app-api/low-score.
RUN python -c "from pvpoke_score_search import load_snapshot, evolution_descendants; assert len(load_snapshot()[1]) == 1153; assert len(evolution_descendants()) == 1025"
COPY start.sh /app/start.sh
COPY volume_bootstrap.sh /app/volume_bootstrap.sh
RUN chmod +x /app/start.sh /app/volume_bootstrap.sh && chown -R appuser:appuser /app
# Initialize the root-owned Railway mount once, then drop to appuser.
USER root
CMD ["/app/volume_bootstrap.sh"]

