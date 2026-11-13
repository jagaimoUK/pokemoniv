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
function validate(input, v2 = false) {
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
      !new Set(["standard", "never", "always", ...(v2 ? ["first"] : [])]).has(input.opponent_shield_rule)) {
    throw Error("Invalid opponent response rule");
  }
  if (typeof input.opponent_attack_rule !== "string" ||
      !new Set(["standard", "charge_if_ready",
        ...(v2 ? ["charge_slot_1", "bank_1", "bank_2"] : [])]).has(input.opponent_attack_rule)) {
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
  const decisionTrace = []; // Causal order, including pre-reveal shield choices.
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
            decisionTrace.push(shieldPrompts.at(-1));
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
      decisionTrace.push({visible, action: selected});
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
  let cmpEqualStatTurns = 0;
  for (const actors of cmpTurns.values()) {
    if (!actors.includes(0) || !actors.includes(1)) continue;
    cmpChecked++;
    if (nativeCmpAttack[0] === nativeCmpAttack[1]) cmpEqualStatTurns++;
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
    decision_trace: decisionTrace,
    self_fast_move_turns: ownFastTurns,
    native_cmp_audit: {simultaneous_charge_turns_checked: cmpChecked,
                       equal_stat_turns_with_no_priority_claim: cmpEqualStatTurns,
                       compared_using_private_native_stats_only: true},
    opponent_attack_rule: input.opponent_attack_rule,
    observed_opponent_event_count: observed.length,
    native_move_events: detail.events.map(e => ({
      turn: e.turn, actor: e.actor, kind: e.kind, move_id: e.move_id,
      shielded: e.shielded
    })),
    observation_provenance_verified: false,
    information_fairness: "not_established",
    live_reproducibility: "not_verified",
    practical_role_covered: false,
  };
}

const V2_FLAGS = {information_fairness: "not_established", live_reproducibility: "not_verified",
  practical_role_covered: false};

function canonicalV2(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalV2).join(",") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonicalV2(value[k])).join(",") + "}";
  }
  return JSON.stringify(value);
}

function runObservedV2(input) {
  const {observed_v2: plan, ...request} = input;
  validate(request, true);
  exact(plan, ["context_hash", "table", "horizon", "branch", "seed"], "replay plan");
  const hashPattern = /^[a-f0-9]{64}$/;
  const actions = ["fast", "charge_0", "charge_1", "wait_one_window", "shield_no", "shield_yes"];
  if (!hashPattern.test(plan.context_hash) || !plan.table || typeof plan.table !== "object" ||
      Array.isArray(plan.table) || Object.keys(plan.table).length > 512 ||
      Object.entries(plan.table).some(([key, action]) => !hashPattern.test(key) || !actions.includes(action))) {
    throw Error("Invalid shared policy");
  }
  bounded(plan.horizon, 1, 500, "horizon");
  bounded(plan.seed, 0, 2147483647, "seed");
  const {branch} = plan;
  exact(branch, ["fast_delay", "miss_first_fast", "reverse_fast_batch"], "delivery branch");
  bounded(branch.fast_delay, 0, 2, "delivery delay");
  if (typeof branch.miss_first_fast !== "boolean" || typeof branch.reverse_fast_batch !== "boolean") {
    throw Error("Invalid delivery branch");
  }
  loadMaster(request.gamemaster_path);
  const {Battle, ActionLogic, TimelineAction} = vm.runInThisContext("({Battle,ActionLogic,TimelineAction})");
  const crypto = require("node:crypto");
  const events = [], intents = [], moves = [], pending = [];
  const stopped = Symbol("bounded replay stop");
  const costs = request.policy.own_charged_moves.map(move => move.energy_cost);
  const shields = request.shields.slice();
  let energy = request.initial[0].energy_points ?? 0;
  bounded(energy, 0, 100, "initial energy");
  let clock = 0, decisionCount = 0, visibleCount = 0, opponentFastCount = 0;
  let opponentBanked = 0, ownCharges = 0;
  let fastGain, status, active, initialState;

  function stop(result) {
    status = result;
    throw stopped;
  }

  function publish(kind, fields = {}) {
    if (kind !== "window" && kind !== "charge_announced" && kind !== "intent" &&
        ++visibleCount > MAX_VISIBLE_EVENTS) stop({status: "unknown", reason: "history_limit"});
    events.push({seq: events.length + 1, observed_time_range: [clock, clock], kind, ...fields});
  }

  function choose(phase) {
    if (++decisionCount > 512) stop({status: "unknown", reason: "history_limit"});
    publish(phase);
    const legal = phase === "window"
      ? actions.slice(0, 4).filter(action => !action.startsWith("charge_") || energy >= costs[Number(action.at(-1))])
      : shields[0] ? actions.slice(4) : ["shield_no"];
    const key = crypto.createHash("sha256")
      .update(canonicalV2(["observed-history-v2", plan.context_hash, events])).digest("hex");
    if (!Object.hasOwn(plan.table, key)) stop({status: "frontier", key, legal, events});
    const action = plan.table[key];
    if (!legal.includes(action)) stop({status: "unknown", reason: "invalid_policy_intent"});
    publish("intent", {action});
    const row = {key, action, window: clock, status: "proposed"};
    intents.push(row);
    return row;
  }

  function wrappedBattle() {
    const battle = new Battle();
    const originalStep = battle.step.bind(battle);
    const originalTurnAction = battle.getTurnAction.bind(battle);
    const originalProcess = battle.processAction.bind(battle);
    const originalUse = battle.useMove.bind(battle);
    const originalStart = battle.start.bind(battle);
    let started = false;
    let inputRow, deliveredCharge;
    let processing = null;
    battle.start = () => {
      originalStart();
      if (started) return;
      started = true;
      const [own, enemy] = battle.getPokemon();
      if ([own, enemy].some(p => p.formChange ||
          [p.fastMove, ...p.chargedMoves].some(m => m.formChange ||
            (m.buffs && m.buffApplyChance !== 1)))) {
        stop({status: "unknown", reason: "unsupported_uncertainty"});
      }
      initialState = [own, enemy].map(p => [p.hp, p.energy, p.shields]);
      fastGain = own.fastMove.energyGain;
      if (own.chargedMoves.slice(0, 2).some((m, i) =>
          m.energy !== costs[i] || m.moveId !== request.policy.own_charged_moves[i].move_id)) {
        throw Error("Invalid public move costs");
      }
    };
    battle.step = () => {
      if (clock >= plan.horizon) stop({status: "complete", outcome: "timeout",
        terminal: battle.getPokemon().map(p => [p.hp, p.energy, p.shields]), intents, moves});
      clock++;
      const batch = pending.filter(item => item.at <= clock);
      if (branch.reverse_fast_batch) batch.reverse();
      for (const item of batch) publish("opponent_fast", {move_id: item.move});
      for (let i = pending.length - 1; i >= 0; i--) {
        if (pending[i].at <= clock) pending.splice(i, 1);
      }
      inputRow = choose("window");
      if (inputRow.action === "wait_one_window") inputRow.status = "no_input";
      originalStep();
      for (const action of battle.getQueuedActions()) {
        if (action.observedIntent?.status === "proposed") action.observedIntent.status = "queued";
      }
      if (inputRow.status === "proposed") inputRow.status = "not_accepted";
    };
    battle.getTurnAction = (own, opponent) => {
      if (own.index !== 0) return originalTurnAction(own, opponent);
      // Returning null here bypasses the engine's automatic fast fallback.
      // For non-wait inputs retain the engine's cooldown and CMP decisions.
      if (inputRow.action === "wait_one_window") return null;
      active = inputRow;
      try {
        return originalTurnAction(own, opponent);
      } finally {
        active = null;
      }
    };
    battle.processAction = (action, own, opponent) => {
      processing = action.observedIntent;
      if (processing) processing.status = action.valid ? "not_resolved" : "cancelled";
      try {
        return originalProcess(action, own, opponent);
      } finally {
        processing = null;
      }
    };
    battle.useMove = (attacker, defender, move, ...rest) => {
      deliveredCharge = null;
      if (move.category === "charged" && attacker.index === 0) ownCharges++;
      if (move.category === "charged" && attacker.index === 1) {
        deliveredCharge = choose("charge_announced");
      }
      // This hook is independent of the generic runner's shield policy.
      battle.shieldPolicy = index => {
        if (index === 0) return deliveredCharge?.action === "shield_yes";
        if (request.opponent_shield_rule === "standard") return undefined;
        return request.opponent_shield_rule === "always" ||
          (request.opponent_shield_rule === "first" && ownCharges === 1);
      };
      const energyBefore = attacker.energy;
      const oldResolved = battle.onMoveResolved;
      battle.onMoveResolved = (actor, target, resolved, damage, shielded) => {
        oldResolved?.(actor, target, resolved, damage, shielded);
        moves.push({actor: actor.index, move: resolved.moveId, kind: resolved.category,
          window: clock, damage, shielded: Boolean(shielded)});
        if (actor.index === 0) {
          if (processing) processing.status = "resolved";
          if (resolved.category === "fast") {
            energy = Math.min(100, energy + fastGain);
            publish("own_fast_resolved");
          } else {
            const slot = actor.chargedMoves.findIndex(m => m.moveId === resolved.moveId);
            energy -= costs[slot];
            publish("own_charge_resolved", {slot});
            if (shielded) {
              shields[1]--;
              publish("opponent_shield_used");
            }
          }
        } else if (resolved.category === "charged") {
          opponentBanked = 0;
          deliveredCharge.status = shielded ? "shield_consumed" :
            deliveredCharge.action === "shield_yes" ? "not_resolved" : "declined";
          if (shielded) {
            shields[0]--;
            publish("own_shield_used");
          }
          publish("charge_revealed", {move_id: resolved.moveId});
        } else {
          const bankMove = actor.chargedMoves[0];
          if (energyBefore >= bankMove.energy || opponentBanked > 0) opponentBanked++;
          const missed = ++opponentFastCount === 1 && branch.miss_first_fast;
          if (!missed) pending.push({at: clock + 1 + branch.fast_delay, move: resolved.moveId});
        }
      };
      try {
        return originalUse(attacker, defender, move, ...rest);
      } finally {
        battle.onMoveResolved = oldResolved;
      }
    };
    return battle;
  }

  const actionLogic = {...ActionLogic, decideAction(battle, own, opponent) {
    if (own.index === 0) {
      if (!active) throw Error("Own intent outside public decision window");
      const charged = active.action.startsWith("charge_");
      const action = new TimelineAction(charged ? "charged" : "fast", 0, battle.getTurns(),
        charged ? Number(active.action.at(-1)) : 0,
        {priority: own.priority, shielded: false, buffs: false, charge: 1});
      action.observedIntent = active;
      if (charged && own.energy >= own.chargedMoves[action.value].energy &&
          own.stats.atk === opponent.stats.atk) {
        // Conservatively exclude equal attack charge cases until both CMP
        // orders can be evaluated, even when a tie would not resolve.
        stop({status: "unknown", reason: "unsupported_uncertainty"});
      }
      return action;
    }
    const rule = request.opponent_attack_rule;
    if (rule !== "standard") {
      const slot = rule === "charge_slot_1" ? 1 : 0;
      const bank = rule === "bank_1" ? 1 : rule === "bank_2" ? 2 : 0;
      const ready = own.energy >= own.chargedMoves[slot].energy;
      const charged = ready && opponentBanked >= bank;
      return new TimelineAction(charged ? "charged" : "fast", own.index, battle.getTurns(), slot,
        {priority: own.priority, shielded: false, buffs: false, charge: 1});
    }
    return ActionLogic.decideAction(battle, own, opponent);
  }};
  // The worker runs one request at a time. Seed the vendor RNG and restore
  // the global function even when a frontier interrupts the simulation.
  const random = Math.random;
  let rng = plan.seed;
  Math.random = () => {
    rng = (Math.imul(1664525, rng) + 1013904223) >>> 0;
    return rng / 4294967296;
  };
  try {
    const detail = strategyRunner({Battle: wrappedBattle, ActionLogic: actionLogic}).run({
      ...request, public_moves: false, bait: [false, false],
    });
    status = {status: "complete", outcome: detail.outcome,
      terminal: detail.terminal.map(p => [p.hp, p.energy_points, p.shields]), intents, moves};
  } catch (error) {
    if (error !== stopped) throw error;
  } finally {
    Math.random = random;
  }
  if (status.status === "complete") {
    for (const row of intents) if (row.status === "queued") row.status = "not_resolved";
  }
  return {schema: "observed-native-v2", ...status,
    ...(status.status === "complete" ? {events, initial: initialState} : {}), ...V2_FLAGS};
}

module.exports = {runObserved, runObservedV2};
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
      const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const result = Object.hasOwn(input, "observed_v2") ? runObservedV2(input) : runObserved(input);
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
