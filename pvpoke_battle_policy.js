'use strict';
// Independent of the UI. All actionable shield decisions receive a copied,
// allowlisted observation, never the incoming move or an engine Pokemon.
const SCHEMA = 'strategy-detail-v1';
function decideShield(o, p) {
  if (o.self.shields <= 0) return false;
  if (p.kind === 'manual') return p.decisions[o.incoming_number - 1] === true;
  if (p.kind !== 'conserve') throw Error('Unsupported observable shield policy');
  const worst = Math.max(0, ...o.possible_charged.map(m => m.damage_upper));
  if (worst >= o.self.hp * p.danger_ratio) return true;
  return o.incoming_number > 1 && o.self.shields > p.reserve && worst >= o.self.hp * .5;
}
function freeze(x) {
  if (x && typeof x === 'object') { Object.values(x).forEach(freeze); Object.freeze(x); }
  return x;
}
function state(p) {
  return {species:p.speciesId, form:p.activeFormId, hp:p.hp, max_hp:p.stats.hp,
    energy_points:p.energy, shields:p.shields, buffs:[...p.statBuffs], cooldown_ms:p.cooldown,
    move_buff_meters:Object.fromEntries([p.fastMove,...p.chargedMoves].filter(m=>m.buffApplyMeter!==undefined).map(m=>[m.moveId,m.buffApplyMeter]))};
}
function createRunner(ctx) {
  const {Battle, createPokemon, DamageCalculator:DC, ActionLogic, TimelineAction, gm} = ctx;
  function run(req) {
    const b = new Battle(); b.setCP(1500);
    const rows = [req.self,req.opponent];
    if (rows.some(r => r.species.startsWith('minior'))) throw Error('Minior policy not supported');
    const ps = rows.map((r,i)=>createPokemon(r,i,b));
    ps.forEach((p,i)=>b.setNewPokemon(p,i,false));
    const initial = req.initial || [{},{}];
    const policies = req.shield_policies || [{kind:'standard'},{kind:'standard'}];
    const attacks = req.attack_policies || ['standard','standard'];
    const bait = req.bait || [true,true];
    ps.forEach((p,i)=>{
      const s=initial[i] || {};
      p.startHp=s.hp_points ?? Math.floor((s.hp_fraction ?? 1)*p.stats.hp);
      p.startEnergy=s.energy_points ?? 0;
      p.startStatBuffs=s.buffs || [0,0];
      p.startCooldown=s.cooldown_ms || 0;
      if (!Number.isInteger(p.startHp) || p.startHp<1 || p.startHp>p.stats.hp) throw Error('Invalid initial HP');
      if (!Number.isInteger(p.startEnergy)||p.startEnergy<0||p.startEnergy>100) throw Error('Invalid energy_points');
      p.setShields(req.shields[i]); p.baitShields=bait[i]?1:0;
      p.optimizeMoveTiming=true;
    });
    const histories=ps.map((p,i)=>({fast_count:0,fast_move:null,charged:[],
      energy_range:initial[i]?.energy_points ? [0,100] : [0,0]}));
    const events=[],decisions=[];
    function observation(defenderIndex) {
      const own=ps[defenderIndex],enemy=ps[1-defenderIndex],h=histories[1-defenderIndex];
      const publicData=gm.getPokemonById(enemy.activeFormId)||gm.getPokemonById(enemy.speciesId);
      const ids=req.public_moves !== false ? [rows[1-defenderIndex].charged1,rows[1-defenderIndex].charged2] :
        [...new Set([...(gm.getPokemonById(enemy.speciesId).chargedMoves||[]),...h.charged.map(m=>m.move_id)])];
      // Public conservative upper bound under CP1500/Lv50; independent of the
      // actual opposing IV, level, energy and secretly selected charged move.
      const base=publicData.baseStats;
      const attackUpper=Math.min((base.atk+15)*.840300023555755,
        Math.sqrt(15010*(base.atk+15)/Math.sqrt(base.def*base.hp)));
      const mult=enemy.getStatBuffMultiplier(0,false); // visible stat stages only
      const publicAttacker={activeFormId:'',getEffectiveStat:()=>attackUpper*mult*(enemy.shadowType==='shadow'?1.2:1),hasTag:()=>false};
      const possible=ids.map(id=>gm.getMoveById(id)).filter(m=>m && m.energy<=h.energy_range[1]).map(m=>{
        m.stab=publicData.types.includes(m.type)?1.2000000476837158:1;
        return {move_id:m.moveId,energy_cost:m.energy,damage_upper:DC.damage(publicAttacker,own,m)};
      });
      return freeze({self:{hp:own.hp,max_hp:own.stats.hp,energy_points:own.energy,shields:own.shields},
        opponent:{species:enemy.speciesId,form:enemy.activeFormId,shields:enemy.shields,
          observed_buffs:[...enemy.statBuffs]},
        observed_fast:{move_id:h.fast_move,count:h.fast_count},
        revealed_charged:h.charged.map(x=>({...x})),estimated_energy_range:[...h.energy_range],
        possible_charged:possible,incoming_number:h.charged.length+1,
        public_moves:req.public_moves!==false,switch_context:req.switch_context||'isolated'});
    }
    b.actionPolicy=(battle,p,op)=>attacks[p.index]==='fast_only' ?
      new TimelineAction('fast',p.index,battle.getTurns(),0,{priority:p.priority}):ActionLogic.decideAction(battle,p,op);
    if(policies.some(p=>p.kind!=='standard')) b.shieldPolicy=(i)=>{
      if(policies[i].kind==='standard')return undefined;
      const o=observation(i),decision=decideShield(o,policies[i]);
      decisions.push({defender:i,turn:b.getTurns(),observation:o,shield:decision,policy:policies[i]});
      return decision;
    };
    b.onMoveResolved=(attacker,defender,move,damage,shielded)=>{
      const i=attacker.index,h=histories[i];
      const charged=move.category==='charged';
      events.push({index:events.length,turn:b.getTurns(),actor:i,kind:charged?'charged':'fast',
        move_id:move.moveId,damage,shielded:!!shielded,target_hp:defender.hp});
      if(charged){
        h.charged.push({move_id:move.moveId,turn:b.getTurns()});
        h.energy_range=h.energy_range.map(e=>Math.max(0,e-move.energy));
      }else{
        h.fast_count++;h.fast_move=move.moveId;
        const gain=attacker.activeFormId==='aegislash_shield' && !move.moveId.startsWith('AEGISLASH_CHARGE')?6:move.energyGain;
        h.energy_range=h.energy_range.map(e=>Math.min(100,e+gain));
      }
    };
    const engineStart=b.start.bind(b);
    b.start=()=>{
      engineStart();
      ps.forEach((p,i)=>{for(const m of [p.fastMove,...p.chargedMoves]){
        const meter=initial[i]?.move_buff_meters?.[m.moveId];
        if(meter!==undefined)m.buffApplyMeter=meter;
      }});
    };
    b.start();
    const start=ps.map(state);
    const baseDamage=ps[0].activeFormId==='aegislash_shield'?1:DC.damage(ps[0],ps[1],ps[0].fastMove);
    let stopped=false;
    if(req.boundary_after_turns !== undefined){
      // Stop only at a neutral boundary. Pending attacks are never discarded.
      for(let turn=0;turn<32;turn++){
        if(b.getTurns()-1>=req.boundary_after_turns && b.getQueuedActions().length===0){stopped=true;break;}
        b.step();
        if(ps.some(p=>p.hp<=0)||b.getDuration()>240000)break;
      }
    }else b.simulate();
    const terminal=ps.map(state);
    let outcome=terminal[0].hp===0&&terminal[1].hp===0?'simultaneous_ko':
      terminal[1].hp===0?'self_ko_win':terminal[0].hp===0?'opponent_ko_win':stopped?'boundary':'timeout';
    const result={schema:SCHEMA,status:'calculated',outcome,turns:b.getTurns()-1,
      elapsed_ms:b.getDuration(),initial:start,terminal,
      rating:Math.floor((terminal[0].hp/terminal[0].max_hp+(terminal[1].max_hp-terminal[1].hp)/terminal[1].max_hp)*500),
      pressure:{damage_per_fast:baseDamage,fast_turns:ps[0].fastMove.turns,
        opponent_max_hp:start[1].max_hp,hp_fraction_per_turn:baseDamage/(ps[0].fastMove.turns*start[1].max_hp)},
      damage:[0,1].map(i=>({fast:events.filter(e=>e.actor===i&&e.kind==='fast').reduce((a,e)=>a+e.damage,0),
        charged:events.filter(e=>e.actor===i&&e.kind==='charged').reduce((a,e)=>a+e.damage,0)})),
      shields_used:start.map((s,i)=>s.shields-terminal[i].shields),events,decisions,
      conditions:{shields:req.shields,bait,attack_policies:attacks,shield_policies:policies,
        public_moves:req.public_moves!==false,timing:'optimal',random_mode:'pvpoke-default-deterministic'},
      boundary_reached:stopped,breakthrough:outcome==='self_ko_win',
      turns_to_breakthrough:outcome==='self_ko_win'?b.getTurns()-1:null};
    return result;
  }
  function switchPrefix(req) {
    if([req.lead,req.safe,req.opponent_lead].some(r=>gm.getPokemonById(r.species).formChange))
      return {status:'unknown',reason:'Form-changing switch state is not supported'};
    const base={shields:req.shields||[2,2],bait:req.bait||[true,true],public_moves:true};
    const opening=run({...base,self:req.lead,opponent:req.opponent_lead,boundary_after_turns:req.lead_turns});
    if(!opening.boundary_reached||opening.terminal.some(p=>p.hp<=0))return {status:'unknown',reason:'No living neutral boundary for the lead switch',opening};
    const shared=opening.terminal.map(p=>p.shields);
    const delay=run({...base,shields:shared,self:req.safe,opponent:req.opponent_lead,
      initial:[{cooldown_ms:1000},toInitial(opening.terminal[1])],boundary_after_turns:req.chase_delay_turns});
    if(!delay.boundary_reached||delay.terminal.some(p=>p.hp<=0))return {status:'unknown',reason:'No living neutral boundary for the counter-switch',opening,delay};
    return {status:'calculated',opening,delay};
  }
  function toInitial(p){return {hp_points:p.hp,energy_points:p.energy_points,buffs:p.buffs,cooldown_ms:p.cooldown_ms,move_buff_meters:p.move_buff_meters};}
  function branch(req) {
    if(gm.getPokemonById(req.chaser.species).formChange)return {status:'unknown',reason:'Form-changing counter-switch state is not supported'};
    const prefix=req.prefix||switchPrefix(req);
    if(prefix.status!=='calculated')return prefix;
    const {opening,delay}=prefix,shared=delay.terminal.map(p=>p.shields);
    const chase=run({shields:shared,bait:req.bait||[true,true],public_moves:true,self:req.safe,opponent:req.chaser,
      initial:[toInitial(delay.terminal[0]),{cooldown_ms:1000}]});
    return {status:'calculated',model:'bounded-lead-switch-counter-v1',opening,delay,chase,
      realized:{lead_turns:opening.turns,chase_delay_turns:delay.turns,
        switch_cooldown_ms:1000,safe_energy_points:delay.terminal[0].energy_points,
        safe_hp:delay.terminal[0].hp,shared_shields_at_chase:shared},
      team_shields_remaining:chase.terminal.map(p=>p.shields),
      benched:{self_lead:opening.terminal[0],opponent_lead:delay.terminal[1]},
      remaining_two_outlook:{status:'unknown',reason:'Resource state only; subsequent switches, farm and 3v3 are not simulated'},
      limitations:['Switches at first neutral boundary at or after requested turn only',
        'Benched lead states are snapshots; switch-out buff/form resets and re-entry are not simulated',
        'No further switches, switch clocks, battle timer or complete 3v3 win probability']};
  }
  return {run,branch,switchPrefix};
}
module.exports={SCHEMA,decideShield,createRunner};
