"use strict";
/**
 * Internal native PvPoke integration harness for a VISIBLE-INPUT proposal.
 *
 * Strictly NOT an app endpoint, PvPoke MCP, practical role evaluator or a
 * verified live player: the real opponent continues to use native AI, whose
 * choices are allowed to depend on its hidden setup. Only OUR action decisions
 * must depend on observed self state and already resolved public events.
 *
 * We reuse the pinned engine by overriding its ActionLogic at the detail
 * runner boundary, NOT by editing the vendor source or saved Sandbox format.
 */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {loadMaster, strategyRunner} = require("./pvpoke_node_matrix.js");

const MAX_INPUT_BYTES = 256 * 1024;
const MAX_OUTPUT_BYTES = 512 * 1024;
const MAX_VISIBLE_EVENTS = 64;
const POLICY = "observable-tactic-proposal-v1";
const RESULT = "observed-native-counterfactual-v1";
const MOVE_ID = /^[A-Z0-9_]{1,100}$/;
const RULES = new Set(["never", "always", "first_announcement"]);

function exact(value, keys, name) {
  if (!value || Array.isArray(value) || typeof value !== "object" ||
      Object.keys(value).length !== keys.length ||
      Object.keys(value).some(key => !keys.includes(key))) throw Error("Invalid " + name);
}
function bounded(value, min, max, label) {
  if (!Number.isSafeInteger(value) || value < min || value > max) throw Error("Invalid " + label);
}
function validate(input) {
  exact(input, ["gamemaster_path", "self", "opponent", "initial", "shields", "policy",
                 "opponent_shield_rule", "opponent_attack_rule"], "native request");
  if (typeof input.gamemaster_path !== "string" ||
      !path.isAbsolute(input.gamemaster_path) || input.gamemaster_path.length > 4096) {
    throw Error("Invalid gamemaster path");
  }
  for (const row of [input.self, input.opponent]) {
    if (!row || typeof row.species !== "string" ||
        /^(aegislash|cramorant|minior)(?:_|$)/.test(row.species)) {
      throw Error("Unsupported dynamic form");
    }
  }
  if (!Array.isArray(input.initial) || input.initial.length !== 2 ||
      !Array.isArray(input.shields) || input.shields.length !== 2) {
    throw Error("Invalid native starting state");
  }
  input.shields.forEach(x => bounded(x, 0, 2, "shields"));
  exact(input.policy, ["own_charged_moves", "energy_reserve", "shield_rule"], "self policy");
  bounded(input.policy.energy_reserve, 0, 30, "reserve");
  if (typeof input.policy.shield_rule !== "string" ||
      !RULES.has(input.policy.shield_rule)) throw Error("Invalid self shield rule");
  if (typeof input.opponent_shield_rule !== "string" ||
      !new Set(["standard", "never", "always"]).has(input.opponent_shield_rule)) {
    throw Error("Invalid opponent response rule");
  }
  if (typeof input.opponent_attack_rule !== "string" ||
      !new Set(["standard", "charge_if_ready"]).has(input.opponent_attack_rule)) {
    throw Error("Invalid opponent attack rule");
  }
  const own = input.policy.own_charged_moves;
  if (!Array.isArray(own) || own.length !== 2) throw Error("Invalid own charged moves");
  own.forEach((m, i) => {
    exact(m, ["move_id", "energy_cost"], "charged move");
    if (typeof m.move_id !== "string" || !MOVE_ID.test(m.move_id)) {
      throw Error("Invalid charged move ID");
    }
    bounded(m.energy_cost, 1, 100, "move energy cost");
    if (m.move_id !== input.self["charged" + (i + 1)]) {
      throw Error("Policy must match exactly the equipped own charged moves");
    }
  });
  if (own[0].move_id === own[1].move_id) throw Error("Duplicate charged move");
}

function frozenClone(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(frozenClone);
    Object.freeze(value);
  }
  return value;
}

function proposeSelf(visible, fixed, nativeMoves) {
  // Own timing/energy and opponent shield count are observable. This function
  // never receives the opponent Pokemon, IV, current energy or queued actions.
  if (visible.phase !== "choose_action" || !visible.own_can_act) {
    throw Error("Native proposal at unexpected phase");
  }
  const selected = nativeMoves.find(move =>
    visible.own_energy >= move.energy + fixed.energy_reserve);
  return selected ? {kind: "charged", move_id: selected.moveId} : {kind: "fast"};
}

function runObserved(input) {
  validate(input);
  loadMaster(input.gamemaster_path);
  // These classes were loaded by the pinned node_matrix into the current VM.
  // Access them without touching its exports or the engine source hashes.
  const native = vm.runInThisContext("({Battle,ActionLogic,TimelineAction})");
  const observed = [];
  const decisions = [];
  const shieldPrompts = [];
  let ownFastTurns = null;
  let nativeCmpAttack = null; // Test-only oracle; NEVER passed to proposeSelf.
  let installed = false;
  const source = input.policy;

  // Wrap only the battle instance in this disposable native harness. A
  // charged-move *announcement* must exist before native shieldPolicy fires.
  // The move's identity is recorded only after onMoveResolved.
  function AuditedBattle() {
    const battle = new native.Battle();
    const nativeUseMove = battle.useMove.bind(battle);
    const nativeProcessAction = battle.processAction.bind(battle);
    let selfActionIndex = null;
    battle.processAction = (action, actor, opponent) => {
      const previous = selfActionIndex;
      const index = action._observed_decision_index;
      if (actor.index === 0 && Number.isInteger(index)) {
        const row = decisions[index];
        if (!row || row.native_process) throw Error("Duplicate observed action");
        row.native_process = {
          turn: battle.getTurns(),
          valid: action.valid === true && !action.processed
        };
        selfActionIndex = index;
      }
      try {
        return nativeProcessAction(action, actor, opponent);
      } finally {
        selfActionIndex = previous;
      }
    };
    battle.useMove = (attacker, defender, move, ...settings) => {
      if (attacker.index === 1 && defender.index === 0 && move.category === "charged") {
        observed.push({turn: battle.getTurns(), kind: "opponent_charge_announced"});
        if (observed.length > MAX_VISIBLE_EVENTS) throw Error("Observation limit exceeded");
      }
      const result = nativeUseMove(attacker, defender, move, ...settings);
      if (attacker.index === 0 && selfActionIndex !== null) {
        const row = decisions[selfActionIndex];
        if (row.native_resolution) throw Error("Duplicate own native move resolution");
        row.native_resolution = {
          turn: battle.getTurns(), kind: move.category, move_id: move.moveId
        };
      }
      return result;
    };

    // This callback is invoked inside the real PvPoke shield decision path,
    // between announcement and resolution. The own policy cannot inspect
    // the incoming move ID because its allowed snapshot has no such field.
    let installedShieldPolicy;
    Object.defineProperty(battle, "shieldPolicy", {
      configurable: true,
      set(fn) { installedShieldPolicy = fn; },
      get() {
        if (!installedShieldPolicy) return undefined;
        return defenderIndex => {
          const snapshot = defenderIndex === 0 ? {
            turn: battle.getTurns(), phase: "shield_prompt",
            own_energy: battle.getPokemon()[0].energy,
            own_shields: battle.getPokemon()[0].shields,
            opponent_shields_visible: battle.getPokemon()[1].shields,
            own_can_act: false,
            events: observed.map(event => ({...event}))
          } : null;
          if (snapshot && (snapshot.events.at(-1)?.kind !== "opponent_charge_announced" ||
                           snapshot.events.at(-1).turn !== snapshot.turn)) {
            throw Error("Self shield prompt must precede charged-move reveal");
          }
          const shield = installedShieldPolicy(defenderIndex);
          if (snapshot) {
            if (shieldPrompts.length >= MAX_VISIBLE_EVENTS) {
              throw Error("Shield prompt budget exceeded");
            }
            const announced = snapshot.events.filter(
              event => event.kind === "opponent_charge_announced").length;
            const expected = snapshot.own_shields > 0 &&
              (source.shield_rule === "always" ||
               (source.shield_rule === "first_announcement" && announced === 1));
            if (shield !== expected) throw Error("Shield decision used nonpublic assumptions");
            shieldPrompts.push({visible: frozenClone(snapshot),
                                action: {kind: "shield", use_shield: shield}});
          }
          return shield;
        };
      }
    });
    return battle;
  }

  const patchedLogic = {
    decideAction(battle, own, opponent) {
      if (own.index !== 0) {
        if (input.opponent_attack_rule === "charge_if_ready" &&
            own.energy >= own.chargedMoves[0].energy) {
          // Explicit opponent counterfactual, never an observed own decision.
          return new native.TimelineAction("charged", own.index, battle.getTurns(), 0,
            {priority: own.priority, shielded: false, buffs: false, charge: 1});
        }
        return native.ActionLogic.decideAction(battle, own, opponent);
      }
      if (!installed) {
        const previous = battle.onMoveResolved;
        if (typeof previous !== "function") throw Error("Missing native resolution hook");
        battle.onMoveResolved = (attacker, defender, move, damage, shielded) => {
          previous(attacker, defender, move, damage, shielded);
          if (attacker.index !== 1) return;
          // A charged move is not revealed to OUR shield decision until after
          // native resolution. Record both historical stages *after* it lands.
          const turn = battle.getTurns();
          if (move.category === "charged") {
            if (observed.at(-1)?.kind !== "opponent_charge_announced" ||
                observed.at(-1).turn !== turn) {
              throw Error("Opponent charged move resolved without public announcement");
            }
            observed.push({turn, kind: "opponent_charge_resolved", move_id: move.moveId});
          } else {
            observed.push({turn, kind: "opponent_fast"});
          }
          if (observed.length > MAX_VISIBLE_EVENTS) {
            throw Error("Observable history budget exceeded");
          }
        };
        installed = true;
      }
      if (ownFastTurns === null) {
        ownFastTurns = own.fastMove.turns;
        // Both stats are used privately by upstream CMP. Keep them outside
        // all public snapshots and all own-policy action decisions.
        nativeCmpAttack = [own.stats.atk, opponent.stats.atk];
      }
      const nativeMoves = own.chargedMoves.slice(0, 2);
      for (let i = 0; i < 2; i++) {
        if (nativeMoves[i]?.moveId !== source.own_charged_moves[i].move_id ||
            nativeMoves[i].energy !== source.own_charged_moves[i].energy_cost) {
          throw Error("Own policy differs from the pinned native GameMaster");
        }
      }
      const visible = frozenClone({
        turn: battle.getTurns(), phase: "choose_action",
        own_energy: own.energy, own_shields: own.shields,
        opponent_shields_visible: opponent.shields, own_can_act: true,
        events: observed.map(event => ({...event}))
      });
      const selected = proposeSelf(visible, source, nativeMoves);
      if (decisions.length >= 500) throw Error("Native decision limit exceeded");
      decisions.push({turn: visible.turn, visible, action: selected});
      const slot = selected.kind === "charged"
        ? nativeMoves.findIndex(move => move.moveId === selected.move_id) : 0;
      const action = new native.TimelineAction(selected.kind, own.index,
        battle.getTurns(), slot, {priority: own.priority, shielded: false, buffs: false, charge: 1});
      action._observed_decision_index = decisions.length - 1;
      return action;
    }
  };
  const ownShields = Array.from({length: 512}, (_, i) =>
    source.shield_rule === "always" ||
      (source.shield_rule === "first_announcement" && i === 0));
  const opponentRule = input.opponent_shield_rule;
  const opponentShields = opponentRule === "standard"
    ? {kind: "standard"}
    : {kind: "manual", decisions: Array(512).fill(opponentRule === "always")};
  const runner = strategyRunner({Battle: AuditedBattle, ActionLogic: patchedLogic});
  const detail = runner.run({
    self: input.self, opponent: input.opponent,
    initial: input.initial, shields: input.shields,
    public_moves: false,
    bait: [false, false],
    attack_policies: ["standard", "standard"],
    shield_policies: [{kind: "manual", decisions: ownShields}, opponentShields],
  });
  const shieldAudits = detail.decisions.filter(d => d.defender === 0).map(d => {
    const own = d.observation.self;
    const expected = own.shields > 0 &&
      (source.shield_rule === "always" ||
       (source.shield_rule === "first_announcement" &&
         d.observation.incoming_number === 1));
    if (expected !== d.shield) throw Error("Native shield decision differs from public rule");
    // The opponent's incoming charged move name and private state are
    // deliberately not copied into our shield decision audit.
    return {turn: d.turn, incoming_number: d.observation.incoming_number,
            own_shields_before: own.shields, used: d.shield,
            chosen_without_move_identity: true};
  });
  const verified = decisions.map(decision => {
    // "Chosen" is not synonymous with "queued", "processed", or "resolved":
    // cooldown, a post-charge lock and CMP/KO can cancel an intended action.
    const resolution = decision.native_resolution || null;
    if (resolution && (resolution.kind !== decision.action.kind ||
        (resolution.kind === "charged" &&
         resolution.move_id !== decision.action.move_id))) {
      throw Error("Native resolved a different self move than the chosen action");
    }
    if (resolution && !detail.events.some(event => event.actor === 0 &&
          event.turn === resolution.turn && event.kind === resolution.kind &&
          event.move_id === resolution.move_id)) {
      throw Error("Native self move resolution is missing from detailed events");
    }
    return {...decision,
      native_process: decision.native_process || null,
      native_resolution: resolution,
      native_resolved_same_turn: Boolean(resolution && resolution.turn === decision.turn)
    };
  });
  const cmpTurns = new Map();
  for (const event of detail.events) {
    if (event.kind !== "charged") continue;
    if (!cmpTurns.has(event.turn)) cmpTurns.set(event.turn, []);
    cmpTurns.get(event.turn).push(event.actor);
  }
  let cmpChecked = 0;
  for (const actors of cmpTurns.values()) {
    if (!actors.includes(0) || !actors.includes(1)) continue;
    cmpChecked++;
    const expectedFirst = nativeCmpAttack[0] > nativeCmpAttack[1] ? 0 :
      nativeCmpAttack[1] > nativeCmpAttack[0] ? 1 : null;
    if (expectedFirst !== null && actors[0] !== expectedFirst) {
      throw Error("Native simultaneous charge priority contradicts upstream CMP stats");
    }
  }

  const actualSelfShields = detail.events.filter(
    event => event.actor === 1 && event.kind === "charged" && event.shielded).length;
  if (actualSelfShields !== shieldPrompts.filter(item => item.action.use_shield).length ||
      actualSelfShields !== detail.shields_used[0]) {
    throw Error("Actual native shield usage differs from pre-reveal decisions");
  }
  return {
    schema: RESULT, information_model: "observed_input_native_experiment",
    status: "counterfactual_only",
    outcome: detail.outcome, turns: detail.turns,
    own_proposals: verified, self_shield_audit: shieldAudits,
    self_shield_prompts: shieldPrompts,
    self_fast_move_turns: ownFastTurns,
    native_cmp_audit: {simultaneous_charge_turns_checked: cmpChecked,
                       compared_using_private_native_stats_only: true},
    opponent_attack_rule: input.opponent_attack_rule,
    observed_opponent_event_count: observed.length,
    native_move_events: detail.events.map(e => ({
      turn: e.turn, actor: e.actor, kind: e.kind, move_id: e.move_id,
      shielded: e.shielded
    })),
    observation_provenance_verified: false,
    live_reproducibility: "not_verified",
    practical_role_covered: false,
  };
}

module.exports = {runObserved};
if (require.main === module) {
  const chunks = [];
  let bytes = 0;
  process.stdin.on("data", chunk => {
    bytes += chunk.length;
    if (bytes > MAX_INPUT_BYTES) {
      process.stderr.write("Native observation request too large\n");
      process.exitCode = 2;
      process.stdin.pause();
    } else chunks.push(chunk);
  });
  process.stdin.on("end", () => {
    if (process.exitCode) return;
    try {
      const result = runObserved(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      const body = JSON.stringify(result) + "\n";
      if (Buffer.byteLength(body) > MAX_OUTPUT_BYTES) {
        throw Error("Native observation output budget exceeded");
      }
      process.stdout.write(body);
    } catch (error) {
      process.stderr.write(String(error.message).slice(0,220) + "\n");
      process.exitCode = 2;
    }
  });
}
