# PvPoke cloud prototype (unpublished)

This is a **single-user** prototype using the existing local PvPoke Matrix automation code. It does not replace PvPoke and does not perform GPT IV selection; ChatGPT does that after reading measured results.

## Deployment outline
1. Upload these files to a private GitHub repository, or use a host that supports directory/Dockerfile deployments.
2. Connect that repo to Railway (or an equivalent host) and create a Dockerfile-backed service.
3. In the host's *secret environment variables* create `PVP_API_KEY`: a random string of **32 or more characters**. Do not put it in a source file, plugin ZIP, or ChatGPT message.
4. Allocate about **2 GB RAM or more** for Chromium. A 512 MB free tier is unlikely to be reliable; check billing before deploying.
5. Enable HTTPS on the host, retain exactly one application replica and stable `PORT`. The platform sets `PORT` if needed.
6. Check `https://YOUR-REAL-HOST/health`. This checks only the Python MCP web server, **not** battle results.
7. From a **trusted local client**, test initialize, tools/list, tools/call with Authorization: `Bearer <YOUR_SECRET>` and a real PvPoke small battle before connecting ChatGPT.
8. Once verified, update the **existing** PvPoke IV Selector plugin's `mcp.json` with that real HTTPS `/mcp` URL, transport and API-key auth. Supply secret via the host's connection flow; never in `mcp.json`.

## Test locally (on a Linux PC with Docker)
`docker build -t pvpoke-cloud .`
`docker run --rm -p 127.0.0.1:8787:8787 -e PVP_API_KEY=<YOUR_RANDOM_SECRET> pvpoke-cloud`

Then send `POST /mcp` with the Authorization header. Requests with missing or incorrect keys return 401.

## Limitations and warnings
- Still a proof of concept. ChatGPT remote MCP compatibility has **not** been verified.
- Uses a small MCP subset, with only JSON and local process state, no durable job ID, cancellation, quotas, or multi-user tenancy.
- Do not publish or make requests before configuring a strong secret and TLS. Secrets must stay in the host's environment settings.
- Docker contains Chromium with `--no-sandbox` from the existing code. Only navigate to the predefined PvPoke page. Host should isolate the container and constrain privileges.
- Result state, caches and files are ephemeral unless a persistent volume is mounted; the same instance must handle status/result calls for an active job.
- The underlying web backend fetches live PvPoke data and requires outgoing internet access.
- Check compatibility, source legitimacy, and PvPoke terms of use before deploying automations at scale.
- Before using for rankings, manually verify level/CP and at least one battle rating for every unique shield scenario.

## Auth0 OAuth integration (experimental)

See `AUTH0_SETUP.md` for how to configure Auth0 and Railway safely. The existing API key remains usable for testing.


## 24-condition curated meta batch (experimental)

The batch option combines 4 automatic opponent IV modes (`default`, `rank1`, `attack`, `defense`) with the existing 6 PvPoke shield situations. It uses the `pvpoke_meta_opponents.csv` snapshot bundled in this private repository. This is a **move-set list only**; source/custom IVs are **never automatically selected**. PvPoke GameMaster supplies the four automatic opponent IV presets.

- Web UI: select your own Pokemon and enter own IVs, then choose **③ メタ全件×4モード×6シールド**.
- MCP: call `prepare_24_conditions` with your candidate and IV lines; then `start_24_conditions`, poll `get_status`, call `get_24_summary` and `get_results` with `mode` and `shield`.
- Headless CLI: `python pvpoke_24_workflow.py --prepare` followed by `python pvpoke_24_workflow.py --run`, reading the most recent web input or a specified `--config` file.

`pvpoke_24_conditions.zip` includes 24 `{mode}_{shield}.csv` files, `ranking_summary.csv`, `opponent_modes_report.csv`, validation exclusions, and a manifest. Battle Ratings above/below 500 in the 24 CSVs are **estimated outcomes**, not PvPoke's original win/loss/draw counters. GPT must evaluate competitive S/A roles from the per-opponent ratings and the intended team context.

The current curated file has 87 source lines. The standard Web UI limit of 80 manual opponents does not apply to this batch feature. Running all scenarios for many candidate IVs can be resource-intensive and may take substantially longer than an ordinary six-condition job. Only one batch job may run at a time.

**Verification**: run unit tests and a small end-to-end PvPoke smoke test before trusting results. Railway build success alone cannot validate battle accuracy. Reconnect/refresh the ChatGPT plugin if its cached MCP tool schema does not expose the new operations.


## Keep the Project meta move list in sync

Railway cannot read ChatGPT Project attachments directly. When the Project file
`pvpokeメタポケモン.txt` changes, export that current file and compare it
with the bundled snapshot before running 24-condition batches:

```bash
python pvpoke_meta_sync.py --source /path/to/pvpokeメタポケモン.txt
# If the diff is correct, write the updated snapshot explicitly:
python pvpoke_meta_sync.py --source /path/to/pvpokeメタポケモン.txt --apply
python -m unittest discover -s tests -v
```

The default command is **read-only** and returns exit code 1 if the lists differ.
`--apply` preserves row order, repeated move sets, shadow spelling and all
four columns. Unexpected extra columns, including embedded IVs, are rejected
rather than silently discarded. After review, commit
`pvpoke_meta_opponents.csv` to GitHub and verify Railway's deployment.
There is **no automatic synchronization** from ChatGPT Project storage: the
current source file must be provided to this command explicitly.
