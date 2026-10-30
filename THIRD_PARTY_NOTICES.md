# Third-party notices

## PvPoke

Upstream: https://github.com/pvpoke/pvpoke
Engine snapshot: `a23fb293300077028a65da534c73bd6367b7ef9d`.
The MIT copyright, permission notice and disclaimer are retained in
`vendor/pvpoke/LICENSE`.

Local `Battle.js` modifications add actionPolicy, shieldPolicy and
onMoveResolved hooks for strategy comparison and move event reporting.
The vendored engine is therefore not an entirely unmodified upstream copy.
Game data fetched separately is not implied to be covered by this engine snapshot.
Approved game data and CP-multiplier source snapshot:
`6477226670913974993c1f7c936331d55cd7d893` (2026-10-29).
Exact SHA-256 values are in `pvpoke_data_snapshot.py`. The engine snapshot and
data snapshot are intentionally tracked separately.

## PokéAPI

`data/flashcard_catalog.json` contains Japanese move names derived from
PokéAPI's `move_names.csv`, imported by `tools/build_flashcard_catalog.py`.
License source: https://github.com/PokeAPI/pokeapi/blob/master/LICENSE.md
Source license Git blob: `293b7db1bd0e64c25619b06e317e9e5373b041aa`.

+Copyright (c) © 2013–2023 Paul Hallett and PokéAPI contributors (https://github.com/PokeAPI/pokeapi#contributing). Pokémon and Pokémon character names are trademarks of Nintendo.

All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.

* Neither the name of PokéAPI nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

## Pokémon names and assets

Pokémon and Pokémon character names are trademarks of Nintendo.
The open source software licenses above do not grant additional rights to
Pokémon trademarks, character artwork or other separately protected assets.
No license for this project's own code is selected by this notice.
