// Run our actual exported CSV through the pinned upstream import implementation.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),{execFileSync}=require('child_process');
const datasets=JSON.parse(execFileSync('python',['-c',`
import json,tempfile
from pathlib import Path
from unittest.mock import patch
import pvpoke_meta_presets as p
import pvpoke_meta_live as live
out=[]
with tempfile.TemporaryDirectory() as d:
 for e in p.bundled()['items']:
  if e.get('available') is False: continue
  data=p.export_preset(Path(d),e['id'],p._content_metadata(e['csv'],True)[0]);out.append(data)
 content='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\\nquagsire_shadow,MUD_SHOT,AQUA_TAIL,MUD_BOMB\\nquagsire_shadow-shadow,MUD_SHOT,AQUA_TAIL,STONE_EDGE\\n'
 with patch.object(live,'active_path') as path:
  path.return_value.read_text.return_value=content
  out.append(p.export_preset(Path(d),'legacy',live.digest(content)))
print(json.dumps(out))
`],{encoding:'utf8'}));
const context={};vm.createContext(context);
vm.runInContext(`let pokemonList=[];const maxPokemonCount=100,battle={getCP(){return 1500}},self={updateListDisplay(){}};
function Pokemon(id){this.speciesId=id;this.shadowType='normal';this.initialize=()=>{};this.selectMove=(kind,move,slot)=>{this[kind+(slot??'')]=move};this.setShadowType=value=>{this.shadowType=value};}`,context);
vm.runInContext(fs.readFileSync('tests/fixtures/pvpoke_quick_fill_csv.js','utf8'),context);
for(const data of datasets){
 let count=0;
 for(const part of data.parts){
  context.quickFillCSV(part.csv);
  const imported=vm.runInContext('pokemonList',context),expected=part.csv.split('\n').map(l=>l.split(','));
  assert.equal(imported.length,expected.length,data.id);
  imported.forEach((p,i)=>{
   const [id,shadow]=expected[i][0].split('-');
   assert.equal(p.speciesId,id);assert.equal(p.shadowType,shadow||'normal');
   assert.equal(p.fast,expected[i][1]);assert.equal(p.charged0,expected[i][2]);assert.equal(p.charged1,expected[i][3]);
  });count+=imported.length;
 }
 assert.equal(count,data.rows);
}
console.log('Actual PvPoke quickFillCSV contract: '+datasets.length+' presets, move variants, shadows and import counts OK');
