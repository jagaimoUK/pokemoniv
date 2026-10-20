"use strict";
const assert = require("node:assert/strict");
const m = require("../pvpoke_minior_strategy.js");

const meteor = {speciesId:"minior_meteor_blue",speciesName:"Minior Meteor Blue",
  baseStats:{atk:116,def:194,hp:155}};
const core = {speciesId:"minior_core_blue",speciesName:"Minior Core Blue",
  baseStats:{atk:218,def:131,hp:155}};
assert.deepEqual(m.resolveForms(meteor,[meteor,core]),
  {meteorId:meteor.speciesId,coreId:core.speciesId});
assert.equal(m.resolveForms({speciesId:"azumarill"},[meteor,core]),null);
assert.throws(()=>m.resolveForms({...meteor,speciesId:"minior_core_blue",speciesName:"Minior Core Blue"},[meteor,core]),/Meteor Form/);
assert.throws(()=>m.resolveForms(meteor,[meteor]),/missing or ambiguous/);

function makePokemon() {
  const pokemon = {
    speciesId:meteor.speciesId, activeFormId:meteor.speciesId,
    stats:{atk:80,def:140,hp:100}, hp:100, energy:65, farmEnergy:false,
    fastMove:{energyGain:8},
    chargedMoves:[{energy:40},{energy:60}],
    activeChargedMoves:[{energy:40},{energy:60}],
    changeForm(id) {
      this.activeFormId=id;
      this.stats.atk=180;
      this.stats.def=90;
    }
  };
  assert.equal(m.preparePokemon(pokemon,{pokemon:[meteor,core]}),true);
  return pokemon;
}
function FakeBattle(poke) {
  this.getPokemon=()=>[poke];
  this.step=()=>null;
  this.getTurnAction=p=>({type:p.farmEnergy?"fast":"charged"});
}
const calculator = {damage:(_att,_def,move)=>move.energy===40?100:8};
const opponent={fastMove:{energyGain:6},hp:150,shields:1};
const poke=makePokemon();
const Hold=m.installBattleHook(function(){return new FakeBattle(poke)},"hold",calculator);
const battle=new Hold();
assert.equal(battle.getTurnAction(poke,opponent).type,"fast");
assert.equal(poke.farmEnergy,false);
poke.hp=50;
battle.step();
assert.equal(poke.activeFormId,meteor.speciesId,"strictly below 50% only");
poke.hp=49;
battle.step();
assert.equal(poke.activeFormId,core.speciesId);
assert.equal(poke.hp,49);
assert.equal(poke.energy,65);
assert.equal(battle.getTurnAction(poke,opponent).type,"charged","attack once transformed");
const adaptive=makePokemon();
assert.equal(m.shouldHold(adaptive,opponent,"adaptive",calculator),true);
adaptive.energy=96;
assert.equal(m.shouldHold(adaptive,opponent,"adaptive",calculator),false,"avoid energy overflow");
adaptive.energy=65;
adaptive.hp=7;
assert.equal(m.shouldHold(adaptive,opponent,"adaptive",calculator),false,"fire if near KO");
adaptive.hp=70;
opponent.shields=0;opponent.hp=50;
assert.equal(m.shouldHold(adaptive,opponent,"adaptive",calculator),false,"fire available lethal charge");
const chosen=m.bestOfPolicies([
  [[500,600,400]],
  [[501,550,400]],
  [[490,610,390]]
]);
assert.deepEqual(chosen,[[{policy:"hold",rating:501},{policy:"adaptive",rating:610},
  {policy:"instant",rating:400}]]);
assert.throws(()=>m.bestOfPolicies([[[1001]],[[50]],[[50]]]),/Invalid strategy/);
console.log("Minior HP threshold, charge policies, energy persistence and oracle selection: PASS");
