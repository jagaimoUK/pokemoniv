"""Check combined patch against an explicitly provided original-project snapshot."""
import json, sys
from pathlib import Path
patch=Path(__file__).resolve().parent.parent
source=Path(sys.argv[1])/'app/src/main/java/com/example/pokemonivreader'
plan=json.loads((patch/'replacements.json').read_text())
def apply(text, changes):
    text=text.replace('\r\n','\n')
    for item in changes:
        if item['after'] in text: continue
        if text.count(item['before'])!=1: raise ValueError('Unsupported source anchor')
        text=text.replace(item['before'],item['after'])
    return text
for name, changes in plan.items():
    result=apply((source/name).read_text(),changes)
    assert apply(result,changes)==result, name
print('All guarded replacements apply idempotently: PASS')
