"""Release preflight: check the Android serializer and fixture against pokemoniv.

Run with: python tools/check_selection_contract.py --selection-root /path/to/pokemoniv
The selection repo runs this exact production Kotlin source in CI and imports
its actual text with the Python parser. Update both copies in the same change.
"""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--selection-root', required=True, type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
for source, destination in [
    ('contracts/iv-text-v1.tsv', 'contracts/iv-text-v1.tsv'),
    ('app/src/main/java/com/example/pokemonivreader/IvSelectionText.kt', 'contracts/reader/IvSelectionText.kt'),
]:
    # Normalize line endings for Windows Android Studio checkouts.
    if (root / source).read_text(encoding='utf-8') != (args.selection_root / destination).read_text(encoding='utf-8'):
        raise SystemExit('受け渡し仕様が一致しません: ' + source)
print('Android exporter and selection CI use the same source and fixtures')
