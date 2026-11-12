# Native observation-only tactics: isolated integration checkpoint

Date: 2026-11-12 (JST), reviewer: GPT-6. This is NOT an independent Astra sign-off.

The original request §7 requires distinguishing hidden opponent moves/IV/energy
from knowledge available in GO before a decision. Source-of-truth engine:
pinned `vendor/pvpoke/src/js/battle/Battle.js` via `pvpoke_node_matrix.js`.
The built-in detail runner already installs an `actionPolicy` that can receive
a private alternative `ActionLogic.decideAction`; this experimental runner
uses this seam without editing the vendor engine, saved Sandbox result format,
standard calculation routes, or any ownership/role state.

## Boundary

- `pvpoke_observed_native_runner.js` is an internal, standalone Node
  **test harness**, not a Web API, deployment service or user feature.
- For actor 0, a small decision function receives only the turn, own energy,
  own shields, visible opponent shields and opponent **already resolved** moves.
  It cannot receive opponent IV, live energy, unrevealed move name or intended
  next action. Native move costs are checked against the pinned GameMaster.
- The opponent uses its usual native PvPoke AI. Therefore it is **not a proof
  of adversarial live-play robustness**: the opponent engine itself can use
  information hidden from a real player.
- The self shield decision uses the existing native detail runner's manual
  override with rule `always`, `never` or `first_announcement`,
  independent of the unrevealed incoming move ID. Historical charge IDs enter
  visible event snapshots only after onMoveResolved, never during shield input.
- The detailed native result is transformed into **counterfactual-only**
  evidence; no ownership, role, IV rank or recommendation changes. No HTTP
  route or persistent schema changes.

## Test gates

- Multiple turns from initial zero energy to native charged-move execution;
  replay logged allowlisted inputs with Python `propose` and require exact
  equality for each own action. Native opponent AI remains pinned.
- Paired counterfactual hidden worlds with different opponent IV and start
  energy, plus opponent shield behavior; first equal visible state yields
  equal self action.
- Invalid hidden input, false own move costs, unselected own move, and
  hidden-move-driven shield policy fail closed before returning evidence.
- No native source changes, saved records, browser/role promotion, or
  user-data accesses. CI result **must** be verified on the final SHA.

## Still incomplete

- Actual GO-time observations versus native trace provenance (including
  real move announcement timing and fast-move start before resolution).
- CMP, post-charge lock, fast timing, charge prompt and shield handling across
  many matchups with 0–2 shields and 1–5 turn fast moves.
- Proper resource limits/owner-scoped resumable exploration for large
  4,096-IV scans and multiple opponent response trees.
- Real ENOSPC, full security reachability, independent Astra review,
  mobile/device checks and safe deployment. Keep Draft, no release.
