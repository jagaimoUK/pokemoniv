"use strict";
// Independent read-only review probes: all Pokemon/GM inputs are synthetic fixtures.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const root = path.resolve(__dirname, "..");
process.env.PVP_PVPOKE_SOURCE = path.join(root, "vendor/pvpoke");
const {loadMaster} = require("../pvpoke_node_matrix.js");
const {runSandbox} = require("../pvpoke_sandbox_runner.js");
const rows = require("./fixtures/strategy_rows.json");
const fixture = path.join(__dirname, "fixtures/strategy_gamemaster.json");

function state(p) {
  return {hp:p.hp, max_hp:p.stats.hp, energy_points:p.energy,
    shields:p.shields, buffs:[...p.statBuffs]};
}

// No runner hooks, preparePokemon, compileActions, simulate, or actionResult.
function nativeOracle(req) {
  loadMaster(req.gamemaster_path);
  const battle = new Battle();
  battle.setCP(1500);
  const pokemon = [req.self, req.opponent].map((row, actor) => {
    const p = new Pokemon(row.species, actor, battle);
    p.ivs = {atk:row.atk, def:row.def, hp:row.hp};
    p.isCustom = true;
    p.setLevel(row.level, false);
    p.initialize(false);
    p.selectMove("fast", row.fast);
    p.selectMove("charged", row.charged1, 0);
    p.selectMove("charged", row.charged2, 1);
    battle.setNewPokemon(p, actor, false);
    const initial = req.initial[actor];
    p.setStartHp(initial.hp_points ?? p.stats.hp);
    p.setStartEnergy(initial.energy_points ?? 0);
    p.setStartBuffs(initial.buffs ?? [0,0]);
    p.setShields(req.shields[actor]);
    return p;
  });
  battle.setSandboxMode(true);
  battle.setActions(req.actions.map(action => new TimelineAction(
    action.kind, action.actor, action.turn,
    action.kind === "charged" ? pokemon[action.actor].chargedMoves.findIndex(m => m.moveId === action.move_id) : 0,
    {priority:0, buffs:false, charge:1, shielded:req.shield_decisions.some(d => d.action_id === action.id && d.use_shield)}
  )));
  const events=[];
  battle.onMoveResolved = (a,d,m,damage,shielded) => events.push({turn:battle.getTurns(),actor:a.index,
    kind:m.category,move_id:m.moveId,damage,shielded:!!shielded,target_hp:d.hp});
  battle.simulate();
  return {terminal:pokemon.map(state), turns:battle.getTurns()-1, rating:battle.getBattleRatings()[0],events};
}

test("independent native oracle: 200 varied scripts, cooldowns 1-5, energy, shields, HP and stages", t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(),"astra-engine-"));
  t.after(() => fs.rmSync(dir,{recursive:true,force:true}));
  let seed=918273;
  const rand=n=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed%n;};
  for(let duration=1;duration<=5;duration++) {
    const gm=JSON.parse(fs.readFileSync(fixture,"utf8"));
    const move=gm.moves.find(m=>m.moveId==="MUD_SHOT");
    move.turns=duration;move.cooldown=duration*500;
    const filename=path.join(dir,`gm-${duration}.json`);
    fs.writeFileSync(filename,JSON.stringify(gm));
    for(let trial=0;trial<40;trial++) {
      const actions=[],shield_decisions=[];
      for(let turn=1;turn<=35;turn++) for(let actor=0;actor<2;actor++) {
        if(rand(3)!==0)continue;
        const row=actor?rows[2]:rows[0],kind=["wait","fast","charged"][rand(3)];
        const action={id:`${actor}-${turn}`,actor,turn,kind};
        if(kind!=="wait")action.move_id=kind==="fast"?row.fast:row[rand(2)?"charged1":"charged2"];
        actions.push(action);
        if(kind==="charged")shield_decisions.push({action_id:action.id,defender:1-actor,use_shield:!!rand(2)});
      }
      const req={gamemaster_path:filename,self:rows[0],opponent:rows[2],actions,shield_decisions,
        initial:[{hp_points:1+rand(164),energy_points:rand(101),buffs:[rand(9)-4,rand(9)-4]},
          {hp_points:1+rand(195),energy_points:rand(101),buffs:[rand(9)-4,rand(9)-4]}],
        shields:[rand(3),rand(3)]};
      const expected=nativeOracle(req),actual=runSandbox(req);
      assert.deepEqual(actual.terminal,expected.terminal,`terminal duration=${duration} trial=${trial}`);
      assert.equal(actual.turns,expected.turns);
      assert.equal(actual.rating,expected.rating);
      assert.deepEqual(actual.events.map(({index,action_id,...event})=>event),expected.events);
      let previous=actual.initial;
      for(const event of actual.trace) {
        assert.deepEqual(event.before,previous,"trace must preserve native state continuity");
        previous=event.after;
        if(event.phase!=="resolve")continue;
        const move=gm.moves.find(m=>m.moveId===event.move_id);
        const energy=event.before[event.actor].energy_points;
        assert.equal(event.after[event.actor].energy_points,
          event.kind==="charged"?energy-move.energy:Math.min(100,energy+move.energyGain));
      }
      assert.deepEqual(previous,actual.terminal);
    }
  }
});

test("exact energy and one below across 1-5-turn fast moves",t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"astra-energy-"));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  for(let duration=1;duration<=5;duration++) {
    const gm=JSON.parse(fs.readFileSync(fixture,"utf8"));
    const fast=gm.moves.find(m=>m.moveId==="MUD_SHOT");
    fast.turns=duration;fast.cooldown=duration*500;
    const cost=gm.moves.find(m=>m.moveId==="AQUA_TAIL").energy;
    const filename=path.join(dir,`gm-${duration}.json`);fs.writeFileSync(filename,JSON.stringify(gm));
    for(const energy of [cost-1,cost]) {
      const actual=runSandbox({gamemaster_path:filename,self:rows[0],opponent:rows[2],shields:[0,0],
        initial:[{energy_points:energy},{}],actions:[{id:"charge",actor:0,turn:1,kind:"charged",move_id:"AQUA_TAIL"}],
        shield_decisions:[]});
      assert.equal(actual.action_results[0].status,energy===cost?"executed":"rejected");
      assert.equal(actual.events.some(e=>e.action_id==="charge"),energy===cost);
    }
  }
});

test("review counterexample: identical scripted throws use different chance-effect semantics in standard and Sandbox",t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),"astra-buff-"));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const gm=JSON.parse(fs.readFileSync(fixture,"utf8"));
  Object.assign(gm.moves.find(m=>m.moveId==="AQUA_TAIL"),{
    buffs:[1,0],buffTarget:"self",buffApplyChance:0.5
  });
  const filename=path.join(dir,"gm.json");fs.writeFileSync(filename,JSON.stringify(gm));
  loadMaster(filename);
  const battle=new Battle();battle.setCP(1500);
  const pokemon=[rows[0],rows[2]].map((row,actor)=>{
    const p=new Pokemon(row.species,actor,battle);p.ivs={atk:row.atk,def:row.def,hp:row.hp};
    p.isCustom=true;p.setLevel(row.level,false);p.initialize(false);
    p.selectMove("fast",row.fast);p.selectMove("charged",row.charged1,0);p.selectMove("charged",row.charged2,1);
    battle.setNewPokemon(p,actor,false);p.setStartEnergy(actor===0?100:0);p.setShields(0);return p;
  });
  battle.actionPolicy=(b,p)=>new TimelineAction(p.index===0&&[1,3].includes(b.getTurns())?"charged":"fast",
    p.index,b.getTurns(),0,{priority:p.priority,buffs:false,charge:1,shielded:false});
  battle.simulate();
  const sandbox=runSandbox({gamemaster_path:filename,self:rows[0],opponent:rows[2],shields:[0,0],
    initial:[{energy_points:100},{}],actions:[1,3].map(turn=>({id:`a${turn}`,actor:0,turn,kind:"charged",move_id:"AQUA_TAIL"})),
    shield_decisions:[]});
  assert.deepEqual(pokemon[0].statBuffs,[1,0]);
  assert.deepEqual(sandbox.terminal[0].buffs,[0,0]);
  assert.notDeepEqual(pokemon.map(state),sandbox.terminal);
  t.diagnostic(JSON.stringify({standard:pokemon.map(state),sandbox:sandbox.terminal}));
});
