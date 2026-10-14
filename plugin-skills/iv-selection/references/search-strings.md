# Pokémon GO IV search strings (English)

## IV value → in-game appraisal search category

Apply the same mapping to Attack, Defense, and HP.

| Actual IV | Search category |
|---|---|
| 0 | 0 |
| 1–5 | 1 |
| 6–10 | 2 |
| 11–14 | 3 |
| 15 | 4 |

## Required format

Write **the whole search query in English**, including the Pokémon's in-game English species name and the appraisal operators:

`EnglishSpecies&Nattack&Ndefense&Nhp`

For Quagsire:

- 0/11/12 → `Quagsire&0attack&3defense&3hp`
- 3/13/8 → `Quagsire&1attack&3defense&2hp`
- 2/15/13 → `Quagsire&1attack&4defense&3hp`
- 0/15/15 → `Quagsire&0attack&4defense&4hp`

Shadow example: `Quagsire&shadow&0attack&3defense&3hp`.

Do not use Japanese names or `こうげき` / `ぼうぎょ` in search queries. PvPoke internal IDs are not necessarily Pokémon GO search tokens, especially for special forms; use the corresponding English in-game name, and when uncertain verify instead of inventing a token. Do not include Pokédex number, `+`, or star appraisal filters `0*` through `4*` unless explicitly requested.

**Important:** These categories are ranges, not exact IV selectors, so multiple Pokémon may match. Never label 1–5 as category 0 or 11–14 as category 2. Verify the specific IV→category mapping before output. Keep one independently copyable search query immediately beneath each recommended Pokémon's rank, IV and explanation. Use Japanese for the explanatory prose, English only for the query.
