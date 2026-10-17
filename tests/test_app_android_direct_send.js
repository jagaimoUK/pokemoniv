const fs=require('fs'),vm=require('vm'),assert=require('assert');
const ui=fs.readFileSync('pvpoke_app_ui.py','utf8');
assert(ui.includes('top:58vh;bottom:auto'),'Thumb shortcut must be above the former bottom location');
assert(ui.includes('min-height:48px;min-width:48px'),'48px touch target required');
const match=ui.match(/function launchAndroidOverlay\(text\)\{[\s\S]*?\n\}/);
assert(match,'Direct Android sender is missing');
const opened=[];
const scope={
 navigator:{userAgent:'Mozilla/5.0 (Linux; Android 16) AppleWebKit Chrome/155.0 Mobile'},
 window:{location:{assign:(url)=>opened.push(url)}},
 TextEncoder,btoa:(raw)=>Buffer.from(raw,'binary').toString('base64')
};
vm.createContext(scope);
vm.runInContext(match[0],scope);
const input=JSON.stringify({format:'pokemoniv-overlay-v2',items:[{search:'Wooper&0attack&3defense&3hp&cp717',nickname:'AQuag>Cor01',ivs:'0/11/12',cp:717}]});
assert.equal(vm.runInContext('launchAndroidOverlay(input)',Object.assign(scope,{input})),true);
assert.equal(opened.length,1);
assert(opened[0].startsWith('intent://import?payload='));
assert(opened[0].endsWith('#Intent;scheme=pokemonivreader;package=com.example.pokemonivreader;end'));
const encoded=opened[0].split('payload=')[1].split('#Intent')[0];
assert.equal(Buffer.from(encoded,'base64url').toString('utf8'),input);
assert.equal(vm.runInContext('launchAndroidOverlay("a".repeat(26001))',scope),false);
assert.equal(opened.length,1);
scope.navigator.userAgent='Mozilla/5.0 (iPhone)';
assert.equal(vm.runInContext('launchAndroidOverlay(input)',scope),false);
console.log('Direct Android launch, IV/CP payload and fallback selection: OK');
