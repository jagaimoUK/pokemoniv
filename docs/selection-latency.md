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

## v0.3.20: server-side tradeoffs and decision-v2

The default decision format now adds a grounded downside example for every candidate where a meaningful difference exists. It scans all opponents and six shields, counts lower-than-best and own<=500/other>500 conditions, and prioritizes focus opponents for the selected example. Each matchup may have a different best candidate; this is not Pareto dominance and never assigns S/A automatically. The model can explain gains and losses from the returned evidence without reconstructing every comparison.

All analyses share one cached sort of each matchup. Decision-v2 preserves every v1 signal, selected example, crossover and focus rating. Repeated opponent labels use each report's zero-based `opponents` dictionary; crossover candidate references use its zero-based `candidate_ivs` dictionary. Tradeoff rows follow `candidate_ivs` order. Integral numbers omit `.0` with no rounding. The skill explicitly decodes both dictionaries per mode. `report_format=decision-v1` and `compact` retain the previous formats. This version also normalizes SHA256 case before verification and rejects matrices whose actual IV set differs from the initiating ticket even if their summary looks valid.

94 tests pass, including complete v1 reconstruction, brute-force tradeoff counts, equal ratings, the 500 boundary, single-candidate batches, focus priority, legacy format, uppercase hash completion, and mismatched matrix rejection. The legacy digest objects still exactly match the original fixtures for 3/12/40/150 candidates. A separate offline skill test decoded a real three-candidate Quagsire report, produced all three recommendations with correct opponent variants, losses and English search strings, and required no extra lookup. The precise subjective S/A order is not a fixed regression expectation.

Compact JSON bytes for the report only, including new tradeoff facts:

| Fixture | v1 bytes | v2 bytes |
|---|---:|---:|
| Synthetic 3 candidates | 4298 | 4114 |
| Synthetic 12 candidates | 6355 | 5675 |
| Synthetic 40 candidates | 10604 | 9853 |
| Synthetic 150 candidates | 27754 | 27588 |
| Real Quagsire 3 candidates, 87 opponents, 6 shields | 6265 | 5368 |

The real report is 14.3% smaller despite the added tradeoffs. Results depend on how much text repeats. These fixtures are not a claim about every possible input or model token count.

Eleven-run local medians for parsing, analysis and encoding (v19/v20): 3 candidates 4.11/5.80 ms; 12 candidates 10.71/14.79 ms; 40 candidates 46.00/39.18 ms; 150 candidates 160.85/198.31 ms. Additional server-side comparison work can increase CPU time slightly; the intended gain is less transmission and less GPT reconstruction/extra retrieval. GPT final-response latency has not been measured in a controlled end-to-end comparison, so no overall percentage is claimed.
