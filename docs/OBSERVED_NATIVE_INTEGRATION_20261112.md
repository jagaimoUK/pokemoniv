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

## Stage: native shield-prompt timing, CMP and post-charge-lock audit

The validation harness uses **only** a wrapped native Battle instance:
`useMove` records the opponent's public charged-move **announcement before**
upstream invokes the native shield decision, while the move ID is appended
**only after** upstream `onMoveResolved` fires. A shield-policy wrapper
captures the exact public observation handed to the fixed self-shield rule;
the pure Python `propose` validates every captured choice. A move's name may
appear later in history after resolution, never on the announcement being
answered. The native engine's GameMaster, battle timing and CMP logic are not
modified. These events are reconstructed from native hooks, **not** verified
real Pokémon GO screenshots or network-visible timestamps.

The native test harness now differentiates `action` (proposal) from
`native_process` (native action validation and processing) and
`native_resolution` (actual executed move). A post-charged-lock proposal
might never be processed; a multi-turn fast move may resolve on a later turn.
The previous `native_resolved_same_turn` indicator remains as a compatibility
alias derived from the actual resolution, not a best-guess event matching.

Test matrix: 0/1/2 shields (five cases), two enemy energy cases, a bounded
explicit `charge_if_ready` opponent counterfactual to force same-turn charge
for CMP resolution evidence, and round-trip between Node's captured pre-reveal
prompt and the independent Python visible-input policy. Opponent scripted
attack selection is deliberately not presented as live-play robustness.

**Known limits:** real-app reveal timing, charge-tap behavior, 1/3/4/5-turn
fast-move fixtures, buff/KO edge cases and exhaustive CMP order across IV
boundaries require additional independent tests. Stable battle outcomes still
do NOT imply robust player policy. This remains a private CI fixture, not
an API, recommendation, role promotion or deployment. Results must be checked
at the final commit SHA; no claims based solely on test author intent.
