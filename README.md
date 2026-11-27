# PvPoke IV selection server and browser app

Current implementation: a single-user PvPoke calculation server, an authenticated browser app with rule-based IV recommendations, and a historical ChatGPT evaluation path (not permitted for current MCP use).

- [Current development handoff (Japanese)](docs/development-handoff.md)
- [Browser input, recommendation and copy behavior](docs/app-selection.md)

## Deployment status: verify the current production target

**Railway is a historical hosting environment, not the current production hosting environment (per the project owner's 2026-11-21 clarification).** The current production provider, production URL, and deployed commit have **not** been independently verified in this document. Do not infer them from an old URL, a deployment guide, the `RAILWAY_VOLUME_MOUNT_PATH` compatibility variable, or an earlier GitHub PR/comment.

Before describing or changing production, confirm the actual active service and deployment revision from its current hosting configuration. Development PRs and CI success do not establish production deployment. Never deploy to a historical Railway target based on this README. Do not merge PRs or deploy to production without explicit approval.

**Safe environment verification (read-only):** identify the current hosting provider and service from its console, record the live URL and deployed revision/commit from that provider, and compare them with the intended GitHub branch and commit. If the live revision cannot be established, report it as *unverified* and stop before any deploy or data operation. A saved Railway GitHub source connection, an old deployment URL, and a successful preview/CI run are not proof of the current production target. The project owner reported disabling Railway Autodeploy on 2026-11-22; this README does not independently verify that setting or imply that manual Railway deployments are disabled.

**Project safety override (2026-11-25):** the historical ChatGPT-connected PvPoke MCP setup and tool-call examples below are retained as archival documentation only. **Do not connect to or use the ChatGPT PvPoke MCP**, including for testing. Use only permitted in-repository calculation and verification paths, and follow the latest default-branch `AGENTS.md` and the active PR handoff.

The links and instructions below include **historical Railway examples**. They are retained for compatibility and provenance, not as evidence of today's production topology. The dated development handoff is a history of earlier implementations, not a live deployment inventory.

## Historical deployment outline (Railway example; not current production)
The following numbered steps describe the historical setup only; do not execute them as current instructions.

1. Upload these files to a private GitHub repository, or use a host that supports directory/Dockerfile deployments.
2. Historical example: connect that repo to Railway (or an equivalent host) and create a Dockerfile-backed service. This is **not** a current production deployment instruction.
3. In the host's *secret environment variables* create `PVP_API_KEY`: a random string of **32 or more characters**. Do not put it in a source file, plugin ZIP, or ChatGPT message.
4. Allocate about **2 GB RAM or more** for Chromium. A 512 MB free tier is unlikely to be reliable; check billing before deploying.
5. Enable HTTPS on the host, retain exactly one application replica and stable `PORT`. The platform sets `PORT` if needed.
6. Check `https://YOUR-REAL-HOST/health`. This checks only the Python MCP web server, **not** battle results.
7. The historical setup included local authenticated protocol and battle tests.
8. The historical plugin used `mcp.json` with an HTTPS `/mcp` endpoint. Do not configure, connect or reconnect the ChatGPT plugin.

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

See `AUTH0_SETUP.md` for historical Auth0/Railway configuration notes; do not assume they match the current deployment. Current credential validity is unverified; credential changes require explicit approval.


## 24-condition curated meta batch (experimental)

The batch option combines 4 automatic opponent IV modes (`default`, `rank1`, `attack`, `defense`) with the existing 6 PvPoke shield situations. It uses the `pvpoke_meta_opponents.csv` snapshot bundled in this private repository. This is a **move-set list only**; source/custom IVs are **never automatically selected**. PvPoke GameMaster supplies the four automatic opponent IV presets.

- Web UI: select your own Pokemon and enter own IVs, then choose **③ メタ全件×4モード×6シールド**.
- Historical MCP interface: `prepare_24_conditions`, `start_24_conditions`, `get_status`, `get_24_summary` and `get_results`. These names document compatibility, not an authorized ChatGPT workflow.
- Headless CLI: `python pvpoke_24_workflow.py --prepare` followed by `python pvpoke_24_workflow.py --run`, reading the most recent web input or a specified `--config` file.

`pvpoke_24_conditions.zip` includes 24 `{mode}_{shield}.csv` files, `ranking_summary.csv`, `opponent_modes_report.csv`, validation exclusions, and a manifest. Battle Ratings above/below 500 in the 24 CSVs are **estimated outcomes**, not PvPoke's original win/loss/draw counters. GPT must evaluate competitive S/A roles from the per-opponent ratings and the intended team context.

The current curated file has 87 source lines. The standard Web UI limit of 80 manual opponents does not apply to this batch feature. Running all scenarios for many candidate IVs can be resource-intensive and may take substantially longer than an ordinary six-condition job. Only one batch job may run at a time.

**Verification**: run unit tests and a small end-to-end PvPoke smoke test before trusting results. Railway build success alone cannot validate battle accuracy. Do not reconnect or refresh the ChatGPT plugin; use permitted repository tests.


## Keep the Project meta move list in sync

The historical Railway service could not read ChatGPT Project attachments directly. When the Project file
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
`pvpoke_meta_opponents.csv` to an authorized development branch. Production deployment requires separate explicit approval and verification of the current host.
There is **no automatic synchronization** from ChatGPT Project storage: the
current source file must be provided to this command explicitly.

## Batch output retention and cleanup

Successful 24-condition calculations now **verify and archive the final ZIP
before removing intermediate CSV files**. The ZIP keeps the 24 per-mode
battle-rating CSVs, ranking summary, opponent IV report and run manifest.
Intermediate Matrix CSV parts, temporary inputs and expanded copies are
deleted **only after** the historical archive and the latest ZIP have both
been written and verified. On ZIP corruption or storage failure, the
intermediate files remain available to diagnose or retry the calculation.

- Without a persistent volume, archives go to
  `~/pvpoke_automation_web/archives/` and do **not** survive Railway redeploys.
- With a Railway volume mounted at `/data`, completed archives go to
  `/data/pvpoke_archives/` (using `RAILWAY_VOLUME_MOUNT_PATH` automatically).
- Optionally set `PVP_ARCHIVE_DIR` to a dedicated persistent directory.
- Each successful run gets a unique `pvpoke_<timestamp>_<id>.zip`; the latest
  archive is copied atomically to `latest.zip` and can be read by MCP
  `get_results` and `get_24_summary` after a server restart.
- Normal six-condition jobs keep their existing behavior; this cleanup is
  limited to the **24-condition batch**. The initial implementation did not automatically delete historical ZIPs; a later retention policy is documented below. Current deployed behavior is unverified.

**Deployment note:** Attaching an empty Railway volume causes a redeployment;
it cannot retroactively rescue ZIPs stored on an earlier deployment's
ephemeral filesystem. Export any important earlier ZIP first.


## Historical Railway volume permissions

Railway mounts volumes as root. The Docker image now starts a minimal
`volume_bootstrap.sh` as root, creates `<mount>/pvpoke_archives`, and
changes ownership of **that directory only** to `appuser`.
It immediately executes the existing `start.sh` as unprivileged
`appuser` through `gosu`; the web server and Chromium never run as root.
The mount directory is read from `RAILWAY_VOLUME_MOUNT_PATH` and must be
an absolute path, not the filesystem root. The historical Railway deployment mounted a volume at `/data`; **the current production mount path is unverified here**.

## One-switch meta batch modes

Use the **メタポケモンとの比較モード** dropdown in the web screen:
- **簡易 (simple)**: PvPoke Default opponent IV only × all six shield cases, 6 rating CSVs.
- **詳細 (detailed)**: Default / Rank 1 / Attack / Defense × all six cases, 24 CSVs.

Both use the same curated meta move list, CP1500 / level 50, ZIP archive retention,
and result tools. The selection changes **opponent IV modes**, not the user's
candidate IVs; no source or custom IV mode is automatically inferred.
Omitting `batch_mode` now runs **simple**, Default opponent IV × 6 shields. Use explicit `batch_mode:"detailed"` for all four opponent IV modes.

Historical MCP interface example (archival only; do not execute through ChatGPT):
```text
prepare_24_conditions({candidate, ivs, batch_mode: "simple"})
start_24_conditions({candidate, ivs, batch_mode: "simple"})
get_status({})
get_24_summary({mode:"default"})
get_results({mode:"default",shield:"s1"})
```
The historical interface accepted `batch_mode:"detailed"` for all 24.
The existing tool names are retained for backward compatibility.
Simple results contain only `default_*.csv` and summary rows for `default`.
The ZIP manifest identifies which mode was used and the archive validator
requires the appropriate six or 24 files. Each run preserves one verified
historical ZIP plus the latest pointer on the volume.

## Historical ChatGPT Project meta sync (disabled as an operational workflow)

The historical Railway service could not independently poll ChatGPT Project files. The former plugin exposed `get_meta_status` and `sync_meta_opponents({csv_text})` for per-request SHA256 comparison and synchronization of complete `species,fast,charged1,charged2` rows. This was not background monitoring. Do not execute this workflow through ChatGPT; use the permitted explicit file-based CLI workflow above.

The server validates all rows against the live GameMaster and rejects
malformed/unknown/duplicate entries without altering the current source.
Successful snapshots are atomically stored at
`<volume>/pvpoke_archives/project_meta_opponents.csv`, surviving a Railway
restart. Meta batch previews and actual runs both use this active snapshot,
falling back to the original bundled `pvpoke_meta_opponents.csv` if nothing
has been synced. Updates are rejected during running jobs. There is no
automatic GitHub commit or modification to the Project file.

`get_storage_status` reports saved historical ZIP counts and size.
After verifying and retaining the new archive, cleanup now preserves the latest
20 run-specific ZIPs within a 200 MiB budget, **always retaining at least the
five newest**, and never deleting `latest.zip`, symlinks, or unrelated files.
Other persistent files such as `project_meta_opponents.csv` are not touched.
Retention is best-effort: an archive cleanup failure never invalidates a
successfully saved, verified ZIP.

# ブラウザだけで個体値厳選

**現在の本番URLはこのREADMEでは未確認です。** 以前のRailway URLを現行アプリとして案内しません。アクセス先は最新の本番デプロイ設定で確認してください。確認済みの環境で既存の接続キーを使用し、
ポケモン・技・個体値を入力すると、全条件の計算から推薦理由と英語検索式まで表示する。
ブラウザから手動コピーした結果のGPT評価は可能。ChatGPT接続PvPoke MCPは使用禁止。自動判定の基準と歴史的な接続仕様は [アプリ推薦](docs/app-selection.md) を参照。

