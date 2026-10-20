"use strict";
/**
 * Experimental Minior PvP policy support.
 * Uses pinned PvPoke's own Battle/Pokemon implementation without rewriting vendor files.
 * HP < 50% transforms after damage, preserving remaining HP and stored energy.
 * No opponent AI or Pokemon GO CP/level correction is inferred here.
 */
const POLICIES = Object.freeze(["instant", "hold", "adaptive"]);
const COLOR = /(?:red|orange|yellow|green|blue|indigo|violet)/i;

function isMinior(id) {
  return /^minior(?:$|[_-])/.test(String(id || "").toLowerCase());
}

function meteorLike(entry) {
  return /meteor/i.test(String(entry?.speciesId || "") + " " + String(entry?.speciesName || ""));
}

function resolveForms(entry, all) {
  if (!isMinior(entry?.speciesId)) return null;
  if (!meteorLike(entry)) {
    throw Error("Minior candidate must start in Meteor Form. Core-form entry scaling is not validated.");
  }
  const family = all.filter(p => isMinior(p.speciesId));
  let core = null;
  const targetId = entry.formChange?.alternativeFormId;
  if (targetId) core = family.find(p => p.speciesId === targetId && !meteorLike(p));
  if (!core) {
    const targetColor = (String(entry.speciesId) + " " + String(entry.speciesName)).match(COLOR)?.[0].toLowerCase() || null;
    const matches = family.filter(p => !meteorLike(p) &&
      /core/i.test(String(p.speciesId) + " " + String(p.speciesName)) &&
      ((String(p.speciesId) + " " + String(p.speciesName)).match(COLOR)?.[0]?.toLowerCase() || null) === targetColor);
    if (matches.length === 1) core = matches[0];
  }
  if (!core) throw Error("Minior Meteor -> Core mapping is missing or ambiguous in active GameMaster.");
  if (!entry.baseStats || !core.baseStats) throw Error("Minior form stats missing");
  if (entry.baseStats.atk >= core.baseStats.atk ||
      entry.baseStats.def <= core.baseStats.def ||
      entry.baseStats.hp !== core.baseStats.hp) {
    throw Error("Minior form stats are inconsistent with Meteor -> Core transition");
  }
  return {meteorId: entry.speciesId, coreId: core.speciesId};
}

function preparePokemon(poke, data) {
  const entry = data.pokemon.find(p => p.speciesId === poke.speciesId);
  const forms = resolveForms(entry, data.pokemon);
  if (!forms) return false;
  if (poke.formChange && poke.formChange.trigger && poke.formChange.trigger !== "hp_threshold") {
    throw Error("Conflicting Minior form rule in GameMaster: " + poke.formChange.trigger);
  }
  poke.originalFormId = forms.meteorId;
  poke.startFormId = forms.meteorId;
  poke.formChange = {trigger:"hp_threshold", alternativeFormId: forms.coreId};
  poke.miniorCoreForm = forms.coreId;
  return true;
}

function shouldHold(poke, opponent, policy, calculator) {
  if (!poke?.miniorCoreForm || poke.activeFormId === poke.miniorCoreForm) return false;
  if (!poke.activeChargedMoves?.length || !poke.fastMove) return false;
  if (poke.energy < Math.min(...poke.activeChargedMoves.map(m => m.energy))) return false;
  if (policy === "hold") return true;
  if (policy !== "adaptive") return false;
  // Keep the charge in reserve unless it is urgent to use it.
  // This heuristic is a third independently simulated tactic, not an oracle.
  if (poke.energy + poke.fastMove.energyGain > 100) return false;
  const enemyDamage = calculator.damage(opponent, poke, opponent.fastMove);
  if (poke.hp <= Math.max(1, enemyDamage)) return false;
  if (opponent.shields === 0 && poke.activeChargedMoves.some(m =>
      poke.energy >= m.energy && calculator.damage(poke, opponent, m) >= opponent.hp)) return false;
  return true;
}

function installBattleHook(originalBattle, policy, calculator) {
  if (!POLICIES.includes(policy)) throw Error("Unknown Minior policy");
  return function MiniorBattle() {
    const battle = new originalBattle();
    const originalTurn = battle.getTurnAction.bind(battle);
    battle.getTurnAction = (poke, opponent) => {
      if (!shouldHold(poke, opponent, policy, calculator)) return originalTurn(poke, opponent);
      const previous = poke.farmEnergy;
      try {
        poke.farmEnergy = true;
        return originalTurn(poke, opponent);
      } finally {
        poke.farmEnergy = previous;
      }
    };
    const originalStep = battle.step.bind(battle);
    battle.step = (...args) => {
      const result = originalStep(...args);
      for (const poke of battle.getPokemon()) {
        if (poke?.miniorCoreForm && poke.hp > 0 &&
            poke.activeFormId !== poke.miniorCoreForm && poke.hp * 2 < poke.stats.hp) {
          const oldEnergy = poke.energy, oldHp = poke.hp, maxHp = poke.stats.hp;
          poke.changeForm(poke.miniorCoreForm);
          if (poke.hp !== oldHp || poke.energy !== oldEnergy || poke.stats.hp !== maxHp) {
            throw Error("Minior transformation must preserve HP, energy, and max HP");
          }
        }
      }
      return result;
    };
    return battle;
  };
}

function bestOfPolicies(results) {
  if (!results.length) throw Error("Missing Minior strategy results");
  const first = results[0];
  return first.map((row, i) => row.map((_, j) => {
    let best = {policy: POLICIES[0], rating: -1};
    for (let n = 0; n < results.length; n++) {
      const rating = results[n][i][j];
      if (!Number.isInteger(rating) || rating < 0 || rating > 1000)
        throw Error("Invalid strategy Battle Rating");
      if (rating > best.rating) best = {policy: POLICIES[n], rating};
    }
    return best;
  }));
}

module.exports = {POLICIES, isMinior, resolveForms, preparePokemon,
                  shouldHold, installBattleHook, bestOfPolicies};
