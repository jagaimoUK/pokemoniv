# Search, reliable queue transport and editable meta presets

## Problems and causes

Nidoran sex labels were treated as literal display-name text, or removed as generic form suffixes, instead of producing a separate GO filter. Search generation now outputs Nidoran&female / Nidoran&male, preserves region/shadow/IV/CP filters, and repairs saved display-suffix queries at the browser copy boundary. The low-score query builder uses the same gender filter helper.

Previous XXL-inclusive UI changes remained in unmerged PR #91 while production still ran the November 3 release. A second source of automatic !xxl was the reader cleanup response builder. Its ordinary exclusion has been removed and excluded_xxl is false. Explicit positive XXL searches remain. The average pumpkin form still needs its deliberate size filters; dropping those would silently include a different stat form. Old broad !xxl exclusions are removed by browser copy/share normalization.

The browser api helper formerly propagated a single Fetch failure out of the whole sequential queue. Production logs include BrokenPipeError at the app response writer, indicating a disconnected client; those logs alone cannot identify whether the network, device or proxy caused the disconnection. The calculation itself may still be running. Retrying a start without an identity could duplicate work.

## Transport recovery and state preservation

Read-only app requests retry transient network errors, truncated JSON and selected transient HTTP statuses up to five times with 750ms exponential backoff capped at 5 seconds. Requests have a 45-second timeout where AbortController exists. Authentication/validation failures and mutation saves are not blindly replayed. Result polling requests wait two seconds instead of twelve, shortening open connections without using zero-wait busy polling.

Every queued start persists a random request ID before sending. IVWorkflow binds that ID to the full original input and its exact run ticket. Duplicate starts return the same ticket, changed input is rejected, and recently superseded IDs cannot restart old work. The retired ID list is bounded to 128; the full input binding is retained only for the current ticket. All requests remain authenticated through the existing app gateway. Backend run_ref/started_at/meta checks remain. No external ChatGPT PvPoke MCP call is involved.

A start whose reply was lost retains its pending ID even when all retries fail, so Resume can recover the same job. Completed results/index/CP and frozen meta are retained. Permanent network outages, auth expiry, server restarts or inconsistent calculation data still pause safely; this is not a promise that calculations continue without a functioning server. Client disconnection during response writing does not cause a secondary attempt to send an error response on the closed socket.

## Meta editor

Select a preset, then open 選択中のメタの内容を編集. A draft shows current opponent rows with Japanese/English Pokémon and legal move suggestions, four clearly labelled fields, and a right-side 44px removal control. Delete has one-step Undo. A name filter and 50-row incremental display bound initial rendering for large metas. Pokémon changes prefill valid moves; unresolved text and duplicate charged moves block saving. Search labels are localized while persisted values remain canonical IDs. Same-name regional ambiguity is not guessed.

Changes remain drafts until Save; cancellation discards the draft. HTTP failure or revision/hash conflict leaves the draft intact. Saves reuse server preview, validation, revision/SHA checks and atomic backup writes. Custom/legacy presets update in place. Official presets save a named editable copy. Editor saves set manual_only so removed opponent rows cannot return through moveset augmentation, including an already queued augmentation applying after the save. Other CSV upload/automatic-comparison flows retain their previous behavior.

## Verification and publication

Added tests cover gender filters, cleanup XXL inclusion, duplicate start identity/input conflicts/superseded IDs, retry/mutation/auth boundaries, lost-start state persistence, exact meta rows and stale augmentation rejection. Node UI tests cover bilingual draft edits, deletion/Undo, copy save and conflict retention. A synthetic local HTTP Chromium fixture checks the editor at 390px and 1280px without running battles. The security workflow runs it inside the existing browser-check image and retains a mobile screenshot.

The previous security gate reported two fixable HIGH findings in apt/libapt-pkg7.0 (3.0.3 -> 3.0.4). The production image explicitly upgrades those packages and asserts the minimum apt version. The scanner and its failure policy remain unchanged; unfixed vulnerabilities are still reported. Browser-test CJK fonts affect only the CI browser image. Full image and browser checks must pass before merge; deploy success and production asset/API checks are required before claiming the site is updated.

The first CI browser run caught editor inputs still disabled after export; rendering now repeats after the loading lock is cleared, with a regression assertion. A backup HTTP test returned 503 in one CI job while passing in others; the old fixture reused the default durable authentication database. Its HTTP credential store and rate budget are now isolated in a temporary fixture, and failed response assertions include the body for diagnosis. This does not establish the precise cause of that earlier transient 503 or change production authentication.

Local tests are followed by grouped PR updates, reusing PR #91 rather than creating parallel feature PRs. The previous main commit/deployment is the rollback reference. Existing persistent schemas remain backward compatible; meta writes preserve .bak files. Actual smartphone GO search behavior, mobile connection conditions and user-specific presets require device confirmation.

## Learning points

An interrupted response and a failed calculation are different events. A stable request identity makes a start safe to retry; blind retrying a write does not. Keep UI drafts separate from persisted data, identify edits by canonical IDs, and use revisions to prevent lost updates. Deleted manual rows must also be protected from background writers, not just removed from the visible DOM. These patterns apply to payment/task queues and collaborative settings editors.
