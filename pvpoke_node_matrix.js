#!/usr/bin/env node
"use strict";
/*
 * Experimental browser-free PvPoke Matrix adapter.
 *
 * Loads UNMODIFIED PvPoke battle engine sources from an independently pinned
 * checkout (PVP_PVPoke_SOURCE). No direct engine results are used in production
 * until exact parity with the browser's TeamRanker Matrix is demonstrated.
 *
 * Protocol: one JSON request per line, one JSON result per line (or --once).
 * Request: {"gamemaster_path":"/.../gamemaster.json","candidates":[...],
 *           "opponents":[...],"shields":[0,1]}
 */
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const readline = require("node:readline");
const minior = require("./pvpoke_minior_strategy.js");

const ROOT = process.env.PVP_PVPOKE_SOURCE || "";
if (!ROOT || !fs.existsSync(path.join(ROOT, "src/js/battle/Battle.js"))) {
  console.error("Missing pinned PvPoke sources at PVP_PVPOKE_SOURCE");
  process.exit(2);
}

let gm, gmDataFile;
const defaults = () => ({
  shields: 1, ivs: "original", bait: 1, levelCap: 50,
  startHp: 1, startEnergy: 0, startCooldown: 0,
  optimizeMoveTiming: true, startStatBuffs: [0, 0]
});
globalThis.getDefaultMultiBattleSettings = defaults;
globalThis.settings = {
  matrixDirection: "row", colorblindMode: 0, hardMovesetLinks: 0
};
globalThis.GameMaster = { getInstance: () => {
  if (!gm) throw Error("GameMaster JSON is not loaded");
  return gm;
} };

const engineFiles = [
  "js/battle/DamageCalculator.js",
  "js/battle/actions/ActionLogic.js",
  "js/battle/timeline/TimelineEvent.js",
  "js/battle/timeline/TimelineAction.js",
  "js/training/DecisionOption.js",
  "js/battle/Battle.js",
  "js/pokemon/Pokemon.js",
  "js/battle/rankers/TeamRanker.js"
];
for (const file of engineFiles) {
  const filename = path.join(ROOT, "src", file);
  vm.runInThisContext(fs.readFileSync(filename, "utf8"), {filename});
}

function buildGM(data) {
  const pokemonMap = new Map(data.pokemon.map(p => [p.speciesId, p]));
  const moveMap = new Map(data.moves.map(m => [m.moveId, m]));
  const cups = new Map((data.cups || []).map(c => [c.name, c]));
  const clone = x => JSON.parse(JSON.stringify(x));
  return {
    data, pokemonMap, moveMap, rankings: {},
    getPokemonById(id) {
      return pokemonMap.get(id);
    },
    getCupById(id) {
      return cups.get(id) || {name:id, include:[], exclude:[]};
    },
    getMoveById(id) {
      if (id === "none") return undefined;
      const m = moveMap.get(id);
      if (!m) throw Error("Unknown move: " + id);
      const abbr = m.abbreviation ||
        m.moveId.split("_").map(s => s.charAt(0)).join("");
      const move = {
        moveId:m.moveId, name:m.name, category:m.category ||
          (m.energyGain > 0 ? "fast" : "charged"),
        displayName:m.name, abbreviation:abbr, archetype:m.archetype || "",
        type:m.type, power:m.power, energy:m.energy,
        energyGain:m.energyGain, damageMethod:m.damageMethod || "default",
        cooldown:m.cooldown, turns:m.turns,
        selfDebuffing:false, selfBuffing:false, selfAttackDebuffing:false,
        selfDefenseDebuffing:false, legacy:false, elite:false,
        instant:false, isMegaMove:!!m.isMegaMove,
        tags: m.tags ? [...m.tags] : [],
        hasTag(tag) { return this.tags.includes(tag); }
      };
      if (id === "RETURN" || id === "FRUSTRATION") {
        move.legacy = true;
        move.displayName += "<sup>†</sup>";
      }
      if (m.buffs) {
        move.buffs = clone(m.buffs);
        move.buffApplyChance = Number(m.buffApplyChance);
        move.buffTarget = m.buffTarget;
        if (move.buffTarget === "both") {
          move.buffsSelf=clone(m.buffsSelf);
          move.buffsOpponent=clone(m.buffsOpponent);
        }
        if (move.buffTarget === "self" && move.buffApplyChance >= .5 &&
            move.moveId !== "DRAGON_ASCENT" &&
            (move.buffs[0] < 0 || move.buffs[1] < 0)) {
          move.selfDebuffing = true;
          move.selfAttackDebuffing = move.buffs[0] < 0;
          move.selfDefenseDebuffing = move.buffs[1] < 0;
        }
        if (move.buffApplyChance === 1 &&
            (move.buffTarget === "opponent" ||
             (move.buffTarget === "self" &&
              (move.buffs[0] > 0 || move.buffs[1] > 0)) ||
             (move.buffTarget === "both" &&
              (move.buffsSelf[0] > 0 || move.buffsSelf[1] > 0)))) {
          move.selfBuffing=true;
        }
      }
      if (m.formChange) move.formChange=clone(m.formChange);
      return move;
    },
    getMoveDataById(id) { return moveMap.get(id); }
  };
}

function loadMaster(filename) {
  if (gmDataFile !== filename) {
    const data = JSON.parse(fs.readFileSync(filename, "utf8"));
    if (!Array.isArray(data.pokemon) || !Array.isArray(data.moves) ||
        !data.settings) throw Error("Incomplete PvPoke GameMaster JSON");
    gm = buildGM(data);
    gmDataFile = filename;
  }
}

function createPokemon(row, index, battle) {
  const required = ["species","fast","charged1","charged2","atk","def","hp","level","cp"];
  for (const key of required) {
    if (row[key] === undefined || row[key] === null) {
      throw Error("Prepared Pokemon is missing: " + key);
    }
  }
  const poke = new Pokemon(row.species, index, battle);
  if (!poke || !poke.speciesId) throw Error("No species: " + row.species);
  poke.ivs.atk = Number(row.atk);
  poke.ivs.def = Number(row.def);
  poke.ivs.hp = Number(row.hp);
  poke.isCustom = true;
  poke.setLevel(Number(row.level), false);
  poke.initialize(false);
  if (poke.cp !== Number(row.cp)) {
    throw Error("CP mismatch: " + row.species + " " + poke.cp + " != " + row.cp);
  }
  poke.selectMove("fast", row.fast);
  poke.selectMove("charged", row.charged1, 0);
  poke.selectMove("charged", row.charged2, 1);
  if (poke.fastMove?.moveId !== row.fast ||
      poke.chargedMoves[0]?.moveId !== row.charged1 ||
      poke.chargedMoves[1]?.moveId !== row.charged2) {
    throw Error("Move import mismatch: " + row.species);
  }
  minior.preparePokemon(poke, gm.data);
  return poke;
}

function matrix(req) {
  if (!Array.isArray(req.candidates) || !req.candidates.length ||
      !Array.isArray(req.opponents) || !req.opponents.length) {
    throw Error("Nonempty prepared candidates and opponents required");
  }
  const shields = req.shields;
  if (!Array.isArray(shields) || shields.length !== 2 ||
      !shields.every(s => Number.isInteger(s) && s >= 0 && s <= 2)) {
    throw Error("shields must be [self,opponent] with 0,1,2");
  }
  loadMaster(req.gamemaster_path);
  const init = new Battle();
  init.setCP(1500);
  const candidates = req.candidates.map((r,i) => createPokemon(r,i,init));
  const opponents = req.opponents.map((r,i) => createPokemon(r,i,init));
  const ranker = RankerMaster.getInstance();
  const selfSettings=defaults(), oppSettings=defaults();
  selfSettings.shields=shields[0];
  oppSettings.shields=shields[1];
  // PvPoke Interface.js sets source group 0 to ranker override 1.
  ranker.applySettings(selfSettings,1);
  ranker.applySettings(oppSettings,0);
  ranker.setTargets(candidates);
  const isMiniorBatch = candidates.some(p => minior.isMinior(p.speciesId));
  const modes = isMiniorBatch ? minior.POLICIES : ["instant"];
  const originalBattle = Battle;
  const allRankings = [];
  let lastRankings = null;
  try {
    for (const policy of modes) {
      // Restore upstream behavior for every non-Minior candidate.
      if (isMiniorBatch) Battle = minior.installBattleHook(originalBattle, policy, DamageCalculator);
      const result = ranker.rank(opponents, 1500, {name:"all",include:[],exclude:[]}, [], "matrix");
      if (!result || !Array.isArray(result.rankings) ||
          result.rankings.length !== candidates.length) {
        throw Error("PvPoke TeamRanker did not return a complete Matrix");
      }
      lastRankings = result.rankings;
      allRankings.push(result.rankings.map(row => {
        if (row.matchups.length !== opponents.length) throw Error("Incomplete opponent matchups");
        return row.matchups.map(m => m.rating);
      }));
    }
  } finally {
    Battle = originalBattle;
  }
  const choices = isMiniorBatch ? minior.bestOfPolicies(allRankings) :
    allRankings[0].map(row => row.map(rating => ({rating,policy:"instant"})));
  const initialNames = req.candidates.map(r => {
    const entry = gm.getPokemonById(r.species);
    return entry.speciesName;
  });
  const opponentNames = req.opponents.map(r => gm.getPokemonById(r.species).speciesName);
  return {
    minior_policy_model: isMiniorBatch ? "experimental-max-per-matchup-v1" : null,
    candidates: isMiniorBatch ? req.candidates.map((r,i) => ({
      label:initialNames[i]+" "+[r.fast,r.charged1,r.charged2].join("/")+" "+
        r.atk+"/"+r.def+"/"+r.hp,
      ratings:choices[i].map(c=>c.rating),
      policies:choices[i].map(c=>c.policy),
      strategy_ratings:Object.fromEntries(modes.map((name,n) => [name,allRankings[n][i]])),
      opponents:req.opponents.map((opp,j) =>
        opponentNames[j]+" "+[opp.fast,opp.charged1,opp.charged2].join("/")+" "+
        opp.atk+"/"+opp.def+"/"+opp.hp)
    })) : lastRankings.map(r => ({
      label:r.pokemon.speciesName+" "+r.pokemon.generateMovesetStr()+" "+
        r.pokemon.ivs.atk+"/"+r.pokemon.ivs.def+"/"+r.pokemon.ivs.hp,
      ratings:r.matchups.map(m=>m.rating),
      opponents:r.matchups.map(m=>m.opponent.speciesName+" "+
        m.opponent.generateMovesetStr()+" "+
        m.opponent.ivs.atk+"/"+m.opponent.ivs.def+"/"+m.opponent.ivs.hp)
    }))
  };
}

async function main() {
  const reader = readline.createInterface({input:process.stdin, crlfDelay:Infinity});
  for await (const line of reader) {
    if (!line.trim()) continue;
    try {
      const req=JSON.parse(line);
      const result=matrix(req);
      process.stdout.write(JSON.stringify({ok:true,result})+"\n");
    } catch (error) {
      process.stdout.write(JSON.stringify({
        ok:false,error:String(error && error.stack || error)
      })+"\n");
    }
  }
}
main().catch(e=>{console.error(e);process.exit(2)});
