# Verified battle reuse and input performance

The raw completed battle ZIP is reused when candidate species/moves, exact ordered IVs, meta CSV content, simple/detailed mode, all six shield cases, CP/level limits, installed game data and calculation code agree. Recommendation policy, focus opponents and output format are analyzed anew from those matrices; no old recommendation is substituted. Changing only report/UI code does not discard valid battles.

Content hashes include GameMaster, CPM/Pokemon.js, all installed PvPoke JS dependencies, our Node/Minior adapters and preparation code. Timestamp-only checks and the old hard-coded engine revision are not sufficient. An unversioned browser engine disables automatic battle/part reuse by default. A direct-to-browser fallback neither merges cached direct hits nor stores fallback results under the direct identity; fallback chunk files are discarded.

New, verified ZIPs populate the result cache; historical ZIPs without a full calculation identity are not retroactively trusted. Restores verify SHA256, ZIP CRCs, required files, candidate/move/IV/mode identity, meta/content version and special strategy evidence. Missing, expired, oversized or corrupt entries fall back to ordinary computation. Cache writes/retention failures must not invalidate a successfully archived calculation. Storage is under the existing private archive volume in result_cache; existing history and latest ZIP retention remain separate.

The UI defaults to automatic reuse and offers “保存結果を使わず再計算”. This snapshot is carried across all jobs and resume. Force recalculation bypasses completed ZIP, matchup SQLite and intermediate CSV caches, then can refresh the completed cache. The response labels successful reuse and still runs current recommendation rules. The existing authenticated, single-user/single-worker model is retained; no new public cache endpoint or background worker is introduced.

| Setting | Default | Effect |
|---|---|---|
| PVP_RESULT_CACHE | 1 | Set 0 to disable completed battle reuse/storage |
| PVP_RESULT_CACHE_TTL_SECONDS | 604800 | Retention/reuse limit, 0 disables; max 30 days |
| PVP_RESULT_CACHE_MAX_ENTRIES | 128 | Bounded entry count (1..512), raised for exhaustive moveset batches |
| PVP_RESULT_CACHE_MAX_MB | 200 | Bounded completed-cache size; max 1024 MB; entry limit below |
| PVP_CACHE_EPOCH | empty | Operator invalidation across both battle cache layers |
| PVP_FORCE_RECALCULATE | 0 | Bypass all battle reuse for newly started jobs |
| PVP_BROWSER_CACHE_EPOCH | empty | Only explicitly pinned browser revisions may reuse |

Version detection observes the data actually installed on the server. It does not automatically download a future upstream update. Updating the installed data or engine changes the content identity and invalidates reuse. An upstream update should be deployed/refreshed using the existing release workflow; forced recalculation alone does not install new game data.

Android v1.4.12 uses session-scoped primary-key item reads, keeps the unchanged queue projection during verified input, updates just the modified item and computes shared-name notes from current checks. Import/resume reopens the source snapshot. Cleanup regexes are compiled once. Tests cover stale sessions, refreshed checks/notes, external reset on resume, 10,000-row indexed reads and prior navigation/reader behavior. Test-runtime measurements are not Android device timing.

Validation includes content changes with identical size/mtime, move/stat/engine/epoch/meta/mode changes, expiry and corruption, restore after reopening, HTTP worker bypass and force override, direct/browser fallback isolation and existing recommendation/transfer regressions. Performance evidence must distinguish real battles, fixture I/O and device measurements.
