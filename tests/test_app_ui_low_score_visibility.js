// The cleanup calculator remains available by explicit deep link, not in the default IV workflow.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync('pvpoke_app_ui.py','utf8');
assert.match(html,/<section class="card" id="lowScorePanel" hidden>/,
 'The non-essential cleanup panel must be hidden before JavaScript runs');
const match=html.match(/function updateLowScorePanelVisibility\(\)\{[\s\S]*?\n\}/);
assert(match, 'Low-score visibility must be controlled by an explicit route');
const panel={hidden:false};
const location={search:''};
const ctx={URLSearchParams,location,el:id=>{assert.equal(id,'lowScorePanel');return panel;}};
vm.createContext(ctx);vm.runInContext(match[0],ctx);
function update(url){location.search=url;vm.runInContext('updateLowScorePanelVisibility()',ctx);return panel.hidden;}
assert.equal(update(''),true);
assert.equal(update('?tool=selection'),true);
assert.equal(update('?tool=low-score-extra'),true);
assert.equal(update('?tool=low-score'),false, 'Legacy cleanup route must remain usable');
assert.equal(update('?from=android&tool=low-score'),false);
assert.equal(update('?tool=low-score&tool=selection'),false);
assert(html.includes('function scoreQueuePayload()'),'Existing cleanup export stays available');
assert(html.includes("api('low-score'"),'Server-side search remains intact');
assert(html.includes('updateLowScorePanelVisibility();const opts='),
 'Visibility must be synchronized when an authenticated workspace opens');
console.log('Low-score cleanup hidden in default mode and preserved via explicit URL: PASS');
