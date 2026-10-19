#!/usr/bin/env python3
"""Refresh the offline form catalog without discarding existing gender/size metadata.
New regional species are discovered from upstream data, not a species allowlist.
The Android app performs the same merge automatically at launch (24-hour interval).
"""
from __future__ import annotations
import argparse, csv, io, json, pathlib, re, urllib.request
ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / 'app/src/main/assets/pokemon_catalog.json'
POKEMON_URL = 'https://raw.githubusercontent.com/pvpoke/pvpoke/master/src/data/gamemaster/pokemon.json'
NAMES_URL = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/master/data/v2/csv/pokemon_species_names.csv'
TYPES = set('normal fire water electric grass ice fighting poison ground flying psychic bug rock ghost dragon dark steel fairy'.split())
TEMPORARY = {'shadow','mega','primal','gigantamax','dynamax'}
LABELS = {'Alolan':'アローラ','Galarian':'ガラル','Hisuian':'ヒスイ','Paldean':'パルデア'}
def read(path, url):
    if path: return pathlib.Path(path).read_text(encoding='utf-8-sig')
    with urllib.request.urlopen(url, timeout=30) as r: return r.read(8*1024*1024).decode('utf-8-sig')
def merge(baseline, upstream, names):
    result = {p['id']:dict(p) for p in baseline}
    accepted=0
    for p in upstream:
        sid=p.get('speciesId',''); name=names.get(p.get('dex')); stats=p.get('baseStats',{})
        if not p.get('released') or not sid or set(sid.split('_')) & TEMPORARY or not name: continue
        ts=list(dict.fromkeys(t for t in p.get('types',[]) if t in TYPES))
        values=[stats.get(k,0) for k in ('atk','def','hp')]
        if not (1 <= len(ts) <= 2 and all(isinstance(v,int) and 1<=v<=1000 for v in values)): raise ValueError('Invalid upstream species: '+sid)
        old=result.get(sid); item=dict(old or {})
        english=p['speciesName']; base=english.split(' (')[0]; qualifier=english.split(' (',1)[1].removesuffix(')') if ' (' in english else ''
        form=item.get('form') or (re.sub('[^a-z0-9]+','_',qualifier.lower()) if qualifier else 'normal')
        item.update(id=sid,dex=p['dex'],ja=item.get('ja') or name,form=form,stats=values,types=ts)
        item['englishNames']=list(dict.fromkeys(item.get('englishNames',[])+[base,english,sid]+([qualifier+' '+base] if qualifier else [])))
        if old is None:
            label=LABELS.get(qualifier,qualifier)
            item.update(display=f'{name}（{label}）' if label else name,next=p.get('family',{}).get('evolutions',[]))
        result[sid]=item; accepted+=1
    if accepted<500: raise ValueError('Incomplete upstream catalog')
    for p in result.values(): p['next']=[i for i in p.get('next',[]) if i in result]
    return list(result.values())
def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--pokemon-file'); cli.add_argument('--names-file'); cli.add_argument('--output',type=pathlib.Path,default=DEST)
    args=cli.parse_args()
    baseline=json.loads(DEST.read_text(encoding='utf-8'))
    rows=list(csv.DictReader(io.StringIO(read(args.names_file,NAMES_URL)))); names={}
    for language in ('1','11'):
        names.update({int(r['pokemon_species_id']):r['name'] for r in rows if r['local_language_id']==language and r['name']})
    result=merge(baseline,json.loads(read(args.pokemon_file,POKEMON_URL)),names)
    tmp=args.output.with_suffix('.tmp'); tmp.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8'); tmp.replace(args.output)
    print(f'Catalog updated: {len(result)} entries; gender, height and export metadata preserved.')
if __name__=='__main__': main()
