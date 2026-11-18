"use strict";
/**
 * Experimental persistent in-memory 1v1 PvPoke stepping adapter.
 * Reuses the existing pinned Battle.js via the established strategy runner.
 * NO production API, 3v3, switching, shield actions, or policy training here.
 * The policy receives only the curated public observation, never engine objects.
 */
const vm = require("node:vm");
const {loadMaster, strategyRunner} = require("./pvpoke_node_matrix.js");
const MAX_TURNS = 500;
const MAX_EVENTS = 1000;
const MAX_INITIAL_BYTES = 128 * 1024;
const ACTIONS = new Set(["wait", "fast", "charge_0", "charge_1"]);

function createStatefulSession(prepared, options = {}) {
  if (!prepared || typeof prepared !== "object" || Array.isArray(prepared) ||
      typeof prepared.gamemaster_path !== "string" ||
      !Array.isArray(prepared.shields) || prepared.shields.length !== 2 ||
      !prepared.self || !prepared.opponent ||
      Buffer.byteLength(JSON.stringify(prepared)) > MAX_INITIAL_BYTES) {
    throw Error("Invalid prepared native battle");
  }
  const horizon = options.horizon ?? MAX_TURNS;
  if (!Number.isSafeInteger(horizon) || horizon < 1 || horizon > MAX_TURNS) {
    throw Error("Invalid horizon");
  }
  // Share PvPoke's initialized battle and damage logic. The capture happens
  // immediately before the established detail runner would auto-simulate.
  loadMaster(prepared.gamemaster_path);
  const {Battle, ActionLogic, TimelineAction} = vm.runInThisContext(
    "({Battle,ActionLogic,TimelineAction})");
  let battle;
  const captured = Symbol("native_battle_captured");
  function CaptureBattle() {
    battle = new Battle();
    battle.simulate = () => { throw captured; };
    return battle;
  }
  const request = {
    self: prepared.self, opponent: prepared.opponent,
    initial: prepared.initial, shields: prepared.shields,
    public_moves: false, bait: [false, false],
    attack_policies: ["fast_only", "standard"],
    shield_policies: [
      {kind: "manual", decisions: Array(512).fill(false)},
      {kind: "standard"},
    ],
  };
  try {
    strategyRunner({Battle: CaptureBattle}).run(request);
    throw Error("Native battle unexpectedly completed during capture");
  } catch (error) {
    if (error !== captured) throw error;
  }
  if (!battle || battle.getTurns() !== 1) throw Error("Native battle was not initialized");
  const pokemon = battle.getPokemon();
  if (pokemon.length !== 2 || pokemon.some(p => !p ||
      p.formChange || [p.fastMove, ...p.chargedMoves].some(m => m.formChange ||
      (m.buffs && m.buffApplyChance !== 1)))) {
    throw Error("Unsupported stochastic or form-changing 1v1 battle");
  }
  // No process-global RNG modification. Stochastic form/buff mechanics are
  // explicitly unsupported by this first experiment.
  const history = [];
  const resolved = battle.onMoveResolved;
  battle.onMoveResolved = (actor, defender, move, damage, shielded) => {
    resolved?.(actor, defender, move, damage, shielded);
    if (history.length >= MAX_EVENTS) throw Error("Observed event limit exceeded");
    history.push(Object.freeze({turn: battle.getTurns(), actor: actor.index,
      kind: move.category, move_id: move.moveId, shielded: Boolean(shielded)}));
  };
  let selected = "wait", done = false, lastCharged = false, thisTurnCharged = false;
  const oldProcess = battle.processAction.bind(battle);
  battle.processAction = (action, actor, defender) => {
    if (action.type === "charged" && action.valid && !action.processed) {
      thisTurnCharged = true;
    }
    return oldProcess(action, actor, defender);
  };
  battle.actionPolicy = (nativeBattle, actor, opponent) => {
    if (actor.index === 1) return ActionLogic.decideAction(nativeBattle, actor, opponent);
    const slot = selected === "charge_0" ? 0 : selected === "charge_1" ? 1 : 0;
    const kind = selected.startsWith("charge_") ? "charged" : selected;
    return new TimelineAction(kind, 0, nativeBattle.getTurns(), slot,
      {priority: actor.priority, shielded: false, buffs: false, charge: 1});
  };
  function observation() {
    const own = pokemon[0], opponent = pokemon[1];
    const canAct = own.cooldown <= 500 && !lastCharged;
    const legal = ["wait"];
    if (canAct) {
      legal.push("fast");
      own.chargedMoves.slice(0, 2).forEach((m, i) => {
        if (own.energy >= m.energy) legal.push("charge_" + i);
      });
    }
    const hpBucket = Math.max(0, Math.min(20,
      Math.round((opponent.hp / opponent.stats.hp) * 20)));
    return {
      turn: battle.getTurns(),
      own: {species: own.speciesId, hp: own.hp, max_hp: own.stats.hp,
        energy: own.energy, shields: own.shields, cooldown_ms: own.cooldown},
      opponent: {species: opponent.speciesId, hp_bucket_5pct: hpBucket,
        shields: opponent.shields},
      legal_actions: legal,
      observed_moves: history.map(e => ({...e})),
      capabilities: {switching: false, manual_shield: false, selection_6v3: false},
    };
  }
  function step(action) {
    if (done) throw Error("Episode has ended");
    const legal = observation().legal_actions;
    if (!ACTIONS.has(action) || !legal.includes(action)) throw Error("Illegal action");
    selected = action;
    thisTurnCharged = false;
    battle.step();
    lastCharged = thisTurnCharged;
    const ownHp = pokemon[0].hp, opponentHp = pokemon[1].hp;
    const terminated = ownHp <= 0 || opponentHp <= 0;
    const truncated = !terminated && (battle.getTurns() - 1 >= horizon ||
      battle.getDuration() > 240000);
    done = terminated || truncated;
    const reward = terminated ? (ownHp > 0 ? 1 : opponentHp > 0 ? -1 : 0) : 0;
    return {
      observation: done ? null : observation(), reward,
      terminated, truncated,
      info: {experimental: true, information_fairness: "not_established",
        live_reproducibility: "not_verified", turns: battle.getTurns() - 1,
        ...(done ? {outcome: terminated ? (reward === 1 ? "self_ko_win" :
          reward === -1 ? "opponent_ko_win" : "simultaneous_ko") : "timeout"} : {})},
    };
  }
  return Object.freeze({observe: () => done ? null : observation(), step});
}
module.exports = {createStatefulSession};
