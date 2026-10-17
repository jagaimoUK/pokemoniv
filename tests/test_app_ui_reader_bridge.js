const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const content=fs.readFileSync('pvpoke_app_ui.py','utf8');
assert(content.includes('<nav class="quick-nav" aria-label="ページ内の移動">'));
assert(content.includes('<a href="#pageTop" aria-label="ページ上部に戻る">'));
assert(content.includes('<main id="pageTop">'));
const receiver=content.match(/function receiveReaderInput\(\)\{[\s\S]*?\n\}\nconst access=/);
assert(receiver,'Reader receiver must be defined before access handling');
const values={importText:{value:''}};
let hash='',url='',notice='',error=false;
const ctx={URLSearchParams,Uint8Array,TextDecoder,atob,
  location:{get hash(){return hash},pathname:'/app',search:'?from=android'},
  history:{replaceState(a,b,c){url=c}},
  el:id=>values[id],
  message:(s,b)=>{notice=s;error=Boolean(b)}
};
vm.createContext(ctx);
vm.runInContext(receiver[0].replace(/\nconst access=$/,''),ctx);
const raw='個体値厳選\n\n# ヌオー\n0,11,12 CP717 | ウパー';
const encoded=Buffer.from(raw,'utf8').toString('base64url');
hash='#ivdata='+encoded;
assert(vm.runInContext('receiveReaderInput()',ctx));
assert.strictEqual(values.importText.value,raw);
assert.strictEqual(url,'/app?from=android');
assert(!error&&notice.includes('受け取りました'));
hash='#ivdata='+Buffer.from('bad','utf8').toString('base64url');
assert(!vm.runInContext('receiveReaderInput()',ctx));
assert(error);
hash='#pageTop'; assert(!vm.runInContext('receiveReaderInput()',ctx));
console.log('Reader IV handoff / invalid payload / back-to-top accessibility: OK');
