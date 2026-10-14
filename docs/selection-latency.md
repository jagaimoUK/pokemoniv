# IV selection latency refactor (v0.3.19)

The battle engine, candidate set and shield conditions are unchanged. This change targets the path from the plugin call to evidence ready for GPT evaluation.

- Parse and validate each six-shield CSV once; share its matrix across ranking, dominance and evidence analysis.
- Bound result polling to 12 seconds by default (0..20 override); never restart a running job.
- Cache only the current run_ref report. Check job identity on each read and after analysis. Clone responses so callers cannot mutate the cache.
- Use microsecond job timestamps to distinguish rapid successive jobs.
- Encode every candidate signal, selected example and crossover highlight as column-defined tables. Keep all values, verification fields, ranking rows and focus ratings. The old digest endpoint and explicit report_format=compact retain the old format.
- Shorten the skill, load references conditionally, and use run_iv_selection's mandatory expected_meta_sha256 guard instead of a redundant metadata preflight. Synchronize only on mismatch.
- Leave S/A judgment and all-candidate review to GPT. No recommendation cap is introduced.

## Validation

87 unittest checks passed. Synthetic 3/12/40/150-candidate x 87-opponent x 6-shield digest objects were exactly equal before and after the parser refactor. The table encoding round-trips all candidate evidence and selected crossovers. The internal analysis also handles more than 87 opponents without the previous 522-highlight cap.

Local benchmark medians (nine samples; milliseconds). Fixtures use synthetic ratings, not actual new PvPoke battles. Timings vary across environments.

| Candidates | Before ms | After ms | Old JSON bytes | Decision JSON bytes |
|---|---:|---:|---:|---:|
| 3 | 4.93 | 3.25 | 6331 | 4298 |
| 12 | 41.51 | 11.33 | 10277 | 6355 |
| 40 | 47.67 | 24.76 | 20002 | 10604 |
| 150 | 155.01 | 129.06 | 60252 | 27754 |

An offline skill test decoded the verified live Quagsire three-candidate result and recommended all three candidates using actual matchup evidence and correct English search strings without extra retrieval.

The server timing field excludes GPT evaluation, model scheduling, tool transport and final text generation. Payload reduction and fewer tool round-trips do not establish an end-to-end latency percentage. Compare the same inputs, model, reasoning effort and cache state over several independent runs before claiming overall speed gains.
