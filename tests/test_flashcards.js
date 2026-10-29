const assert=require('assert'),C=require('../flashcards_core.js');
const cat={species:{a:{fast:['F','G'],charged:['X','Y','Z']}},moves:{F:{gain:9},G:{gain:7},X:{cost:40},Y:{cost:55},Z:{cost:100}}};
const card={species:'a',fast:'F',charged:'X'};
assert.deepEqual(C.counts(9,40),[5,4,5,4]);
assert.deepEqual(C.counts(7,100),[15,15,15,15]); // 100-energy cap discards overflow.
for(const invalid of [0,-1,101,NaN,Infinity])assert.throws(()=>C.counts(invalid,40));
for(const invalid of [0,-1,101,NaN,Infinity])assert.throws(()=>C.counts(9,invalid));
assert.equal(C.cards([{species:'a',fast:['F','G'],charged:['X','Y','Z']}],cat).items.length,6);
assert.equal(C.cards([{species:'missing',fast:['F'],charged:['X']}],cat).invalid,1);
const start=C.stateFor(card,null,cat.moves);let s=C.review(start,true,1000);
assert.equal(s.due,1000+C.DAY);assert.equal(s.reps,1);
const early=C.review(s,true,2000);assert.equal(early.due,s.due);assert.equal(early.reps,1);
s=C.review(s,true,s.due);assert.equal(s.interval,6);s=C.review(s,true,s.due);assert.equal(s.interval,15);
s=C.review(s,false,s.due);assert.equal(s.reps,0);assert.equal(s.lapses,1);assert.equal(s.due-s.last,600000);
assert.equal(C.stateFor(card,s,cat.moves).seen,s.seen);
assert.equal(C.stateFor(card,s,{...cat.moves,F:{gain:8}}).seen,0);
const updated=C.mergeDecks([{id:'meta:x',extra:[{species:'a',fast:['G'],charged:['Z']}],excluded:['a|F|X']}],[{id:'meta:x',rows:[{species:'a',fast:['F'],charged:['X','Y']}]}]);
assert.equal(C.deckCards(updated[0],cat).items.length,2);
assert.equal(C.mergeDecks([{id:'meta:legacy',revision:'private',rows:['saved']}],[{id:'meta:legacy',rows:['bundled']}])[0].revision,'private');
const many=Array.from({length:12000},(_,i)=>({...card,species:'a'+i}));
let records={};for(let i=0;i<60;i++)records[C.key(many[i])]={...start,id:C.key(many[i]),seen:1,due:1000,lapses:i===30?8:0};
for(const limit of [10,30,50])assert.equal(C.select(many,records,cat.moves,limit,2000).length,limit);
assert.equal(C.key(C.select(many,records,cat.moves,10,2000)[0]),C.key(many[30]));
const t=performance.now();for(let i=0;i<20;i++)C.select(many,records,cat.moves,50,2000);console.log('12,000 cards select50, avg ms:',((performance.now()-t)/20).toFixed(2));
assert.equal(C.dueInfo([{rows:[{species:'a',fast:['F'],charged:['X']}]}],cat,{[C.key(card)]:s},s.due).due,1);
console.log('Flashcards: counts/cap, invalid energy, multi-moves, SM-2/relearning/early practice, change invalidation, merge/history, due/hard priority and 12k-card limit: PASS');

assert.deepEqual(C.afterHeavy(9,40,55),{first:7,remaining:8,counts:[7,4,4,5]});
assert.deepEqual(C.alternatives({...card,heavy:['Y','Z']},cat.moves)[0].counts,[7,4,4,5]);
assert.deepEqual(C.alternatives({fast:'F',charged:'X',heavy:['Y']},{F:{gain:8},X:{cost:40},Y:{cost:55}}),[]);
assert.deepEqual(C.afterHeavy(7,35,100).counts,[15,5,5,5]);
for(let gain=1;gain<=20;gain++)for(const cost of [35,40,55,70])for(const heavy of [75,90,100]){
 let energy=0,n=0;while(energy<heavy){energy=Math.min(100,energy+gain);n++;}energy-=heavy;
 const expected=[n];for(let i=1;i<4;i++){let count=0;while(energy<cost){energy=Math.min(100,energy+gain);count++;}energy-=cost;expected.push(count);}
 assert.deepEqual(C.afterHeavy(gain,cost,heavy),{first:n,remaining:Math.min(100,n*gain)-heavy,counts:expected});
}
const shadowCat={...cat,species:{...cat.species,a_shadow:cat.species.a,a_galarian:cat.species.a}};
const duplicates={rows:[{species:'a_shadow',fast:['F','G'],charged:['X','Y']},{species:'a',fast:['F'],charged:['X']},{species:'a_galarian',fast:['F'],charged:['X']}]};
const unique=C.deckCards(duplicates,shadowCat).items;
assert.equal(unique.length,6);assert(unique.some(c=>c.species==='a'&&c.fast==='F'&&c.charged==='X'));assert(unique.some(c=>c.species==='a_shadow'&&c.fast==='G'));assert(unique.some(c=>c.species==='a_galarian'));
const shadowReview={...start,id:'a_shadow|F|X',seen:8,last:200,due:400};assert.equal(C.reviewState(card,{'a_shadow|F|X':shadowReview},cat.moves).seen,8);assert.equal(C.reviewState(card,{'a_shadow|F|X':shadowReview},cat.moves).id,'a|F|X');
const original=[card,{...card,charged:'Y'},{...card,charged:'Z'}];const mixed=C.shuffle(original,()=>.999);assert.notDeepEqual(mixed,original);assert.deepEqual(new Set(mixed.map(C.key)),new Set(original.map(C.key)));assert.equal(original[0],card);
console.log('4 counts, heavy-first residual/cap (240 scenarios), unchanged paths, shadow dedup/forms/history and replay shuffle: PASS');

// Compare the same charged-attack positions, not target-use indices after the opener.
const catalog=require('../data/flashcard_catalog.json');
const ape={species:'annihilape',fast:'COUNTER',charged:'ICE_PUNCH',heavy:['CLOSE_COMBAT','SHADOW_BALL']};
assert.deepEqual(C.counts(6,40),[7,7,6,7]);
assert.deepEqual(C.afterHeavy(6,40,45).counts,[8,7,6,7]);
assert.deepEqual(C.alternatives({...ape,heavy:['CLOSE_COMBAT']},catalog.moves),[]);
assert.deepEqual(C.alternatives(ape,catalog.moves).map(a=>({moves:a.moves,counts:a.counts})),
 [{moves:['SHADOW_BALL'],counts:[9,6,7,7]}]);
for(let gain=1;gain<=20;gain++)for(const cost of [35,40,55,70])for(const heavy of [75,90,100]){
 const moves={F:{gain},X:{cost},Y:{cost:heavy}},normal=C.counts(gain,cost);
 const mixed=C.afterHeavy(gain,cost,heavy).counts;
 const changed=mixed.slice(1).some((v,i)=>v!==normal[i+1]);
 assert.equal(C.alternatives({fast:'F',charged:'X',heavy:['Y']},moves).length,Number(changed));
}
console.log('Annihilape Counter/Ice Punch/Close Combat: omit unchanged attacks 2–4; Shadow Ball mixed sequence; 240 positional comparisons: PASS');

// An independent cumulative-energy oracle for arbitrary four-attack orders.
let scenarios=0;
for(let gain=1;gain<=20;gain++)for(const a of [35,50,100])for(const b of [40,45,100])for(const c of [35,60])for(const d of [45,100]){
 const costs=[a,b,c,d];let energy=0;const expected=[];
 for(const cost of costs){let used=0;while(energy<cost){energy=Math.min(100,energy+gain);used++;}energy-=cost;expected.push(used);}
 assert.deepEqual(C.sequenceCounts(gain,costs),expected);scenarios++;
}
for(const costs of [[],[40],[40,40,40,0],[40,40,40,101],null])assert.throws(()=>C.sequenceCounts(6,costs));
const forward={species:'a',fast:'F',charged:'X',sequence:['X','X','Y','Y']},reverse={...forward,charged:'Y',sequence:['Y','Y','X','X']};
assert.notEqual(C.key(forward),C.key(reverse));assert.notEqual(C.key(forward),C.key(card));
assert.equal(C.key({...card,sequence:['X','X','X','X']}),C.key(card));
assert.equal(C.signature({...card,sequence:['X','X','X','X']},cat.moves),C.signature(card,cat.moves));
assert.equal(C.reviewState(reverse,{[C.key(forward)]:{...start,signature:C.signature(forward,cat.moves),seen:9}},cat.moves).seen,0);
const learnedPath={...C.stateFor(forward,null,cat.moves),seen:5};
assert.equal(C.stateFor(forward,learnedPath,{...cat.moves,Y:{cost:60}}).seen,0);
const sequences={id:'meta:x',rows:[],extra:[{species:'a',fast:['F'],charged:['X','Y'],sequences:[forward.sequence,reverse.sequence]}],excluded:[]};
assert.equal(C.deckCards(sequences,cat).items.length,2);
assert.equal(C.deckCards({...sequences,excluded:[C.key(forward)]},cat).items.length,1);
assert.equal(C.deckCards(C.mergeDecks([sequences],[{id:'meta:x',rows:[]}])[0],cat).items.length,2);
assert.equal(C.cards([{species:'a',fast:['F'],charged:['X'],sequences:[['X','X','X','missing']]}],cat).invalid,1);
assert.deepEqual(C.relativeCounts([9,9,9,8],2),[4,5,4,4]);
assert.deepEqual(C.relativeCounts([9,9,9,8],3),[3,3,3,2]);
assert.deepEqual(C.relativeCounts([9,9,9,8],4),[2,2,2,2]);
assert.deepEqual(C.relativeCounts([9,9,9,8],5),[1,2,2,2]);
for(const turns of [2,3,4,5])assert.equal(C.relativeCounts([9,9,9,8],turns).reduce((a,b)=>a+b),Math.floor(35/turns));
const sandshrew={species:'sandshrew',fast:'SAND_ATTACK',charged:'ROCK_TOMB',sequence:['ROCK_TOMB','ROCK_TOMB','SAND_TOMB','SAND_TOMB']};
assert.deepEqual(C.answer(sandshrew,catalog.moves),[13,12,12,11]);
const apeQuestions=C.deckCards({rows:[{species:'annihilape',fast:['COUNTER'],charged:['ICE_PUNCH','CLOSE_COMBAT','SHADOW_BALL']}]},catalog).items;
assert(apeQuestions.some(c=>c.sequence?.join('>')==='SHADOW_BALL>ICE_PUNCH>ICE_PUNCH>ICE_PUNCH'));
assert(!apeQuestions.some(c=>c.sequence?.join('>')==='CLOSE_COMBAT>ICE_PUNCH>ICE_PUNCH>ICE_PUNCH'));
console.log('Explicit four-move orders, '+scenarios+' cap/residual cases, independent history, restore/sync/exclusion, turns with carried remainder: PASS');
