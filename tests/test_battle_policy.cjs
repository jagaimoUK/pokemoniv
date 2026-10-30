'use strict';
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
process.env.PVP_PVPOKE_SOURCE=path.resolve(__dirname,'../vendor/pvpoke');
const adapter=require('../pvpoke_node_matrix.js');
adapter.loadMaster(path.join(__dirname,'fixtures/strategy_gamemaster.json'));
const rows=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/strategy_rows.json')));
const {decideShield}=require('../pvpoke_battle_policy.js');
const p={kind:'conserve',danger_ratio:.95,reserve:1};
const o={self:{hp:100,shields:2},incoming_number:1,possible_charged:[{damage_upper:50}]};
assert.equal(decideShield(o,p),false);assert.equal(decideShield({...o,possible_charged:[{damage_upper:100}]},p),true);
assert.equal(decideShield({...o,incoming_number:2},p),true);
assert.equal(decideShield({...o,self:{hp:100,shields:1},incoming_number:2},p),false);
assert.equal(decideShield(o,{kind:'manual',decisions:[true]}),true);
// Two real engine runs: force a DIFFERENT hidden move on turn 1. Same public
// species, fast history, own state, and unknown starting enemy energy.
function experiment(slot,policy){
 const logic={decideAction(b,poke){return {type:poke.index===1&&poke.energy>=poke.chargedMoves[slot].energy?'charged':'fast',actor:poke.index,turn:b.getTurns(),value:slot,settings:{priority:poke.priority},valid:false,processed:false}}};
 const runner=adapter.strategyRunner({ActionLogic:logic});
 return runner.run({self:rows[2],opponent:rows[1],shields:[2,0],initial:[{},{energy_points:100}],
   public_moves:false,shield_policies:[policy,{kind:'standard'}]});
}
for(const policy of [p,{kind:'manual',decisions:[false,true]}]){
 const a=experiment(0,policy),b=experiment(1,policy);
 assert.notEqual(a.events.find(e=>e.actor===1&&e.kind==='charged').move_id,b.events.find(e=>e.actor===1&&e.kind==='charged').move_id);
 assert.deepEqual(a.decisions[0].observation,b.decisions[0].observation);
 assert.equal(a.decisions[0].shield,b.decisions[0].shield);
 const text=JSON.stringify(a.decisions[0].observation);
 for(const key of ['incoming_move','exact_damage','opponent_energy','chargedMoves','ivs','level'])assert(!text.includes('"'+key+'"'));
 assert(Object.isFrozen(a.decisions[0].observation));
}
// Request-level attack policy cannot leak into the next run.
const runner=adapter.strategyRunner();
const base={self:rows[0],opponent:rows[1],shields:[2,2]};
const a=runner.run(base);runner.run({...base,attack_policies:['fast_only','standard']});const b=runner.run(base);
assert.deepEqual(a,b);
console.log('Observable shield invariance, manual policy and policy isolation passed');
