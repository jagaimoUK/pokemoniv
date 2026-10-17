# Observed CP and compact overlay integration

Reader exports use `ATK,DEF,HP CP<number> | <captured species ID>`; the existing
plain-IV commands still work. CP is observed on the captured Pokemon, and must
never come from a powered-up/evolved simulation result. Import groups deduplicate
simulation IVs while retaining different observed CPs and source species. The
browser's resumable batch state retains `source_records`; changing a single
form's species or IV input detaches the old CP metadata.

All GO search copies expand each IV into its observed individuals, using the
original species and exact CP. `source_cp` and optional `source_species` CSV
columns are explicit observed metadata; a generic simulation `cp` is ignored.

The old all-copy output remains exactly search/newline/nickname pairs. Android
share and the dedicated overlay-copy action use `pokemoniv-overlay-v2` JSON with
exact IVs. The importer accepts both, validates the full import before writing,
and preserves duplicate pairs. Legacy pairs show truthful IV ranges; exact IVs
cannot be reconstructed from their bucket searches. SQLite v2 adds nullable
`ivs` while preserving old sessions, checks, counts, and timestamps.

The selection panel is at most 240dp wide / 280dp high, capped to 62% screen
width / 32% height. It stays unfocused; bounded-window outside-touch events
collapse it. The bubble is hidden while the panel is visible. The overlay has
search/name buttons, an IV/CP title, progress, and Stop. Stop or bubble long press
removes both selection windows, without stopping the independent OCR service.
Completed rows remain visible and can be copied repeatedly. The import Activity
provides close/stop controls and historical session selection, and returns the
app to the background after showing the overlay.

`android-integration/Apply-CP-CompactOverlay.ps1` updates six files in the user's
original Android Studio project, checks canonical source hashes first, keeps a
backup, resolves Android Studio JBR, builds, and restores changed source on build
failure. It deliberately requires an existing integrated overlay project. It
does not replace the full project, manifest, Gradle settings, or MainActivity.

Validation before release: local app tests (64), grouped/import contract tests,
observed-CP cases, migration against the original v1 SQLite schema, and Node UI
regressions pass. Android harness assembleDebug and four Kotlin transfer tests
passed in run 39009264038. The final full unit suite (182 tests) and real
GameMaster previews passed in run 39009435303. This does not claim a build on the
user's original Windows project or new actual-device UI success; those checks
must occur after installing the update. The earlier six successful device
checks in the previous handoff remain historical results.

Change review: https://github.com/jagaimoUK/pokemoniv/pull/33
