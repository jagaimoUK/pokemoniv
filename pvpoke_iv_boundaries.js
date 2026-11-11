"use strict";

const path = require("node:path");
const {loadMaster} = require("./pvpoke_node_matrix.js");

const MAX_CANDIDATES = 4096;
const MAX_CONDITIONS = 6;
const MAX_INPUT_BYTES = 3 * 1024 * 1024;
const CP_CAP = 1500;
const MAX_LEVEL = 50;

function preparePokemon(row, index, battle, gameMaster) {
  if (!row || typeof row.species !== "string" || !/^[a-z0-9_]{1,100}$/.test(row.species) ||
      ![row.fast, row.charged1, row.charged2].every(id =>
        typeof id === "string" && /^[A-Z0-9_]{1,100}$/.test(id)) ||
      row.charged1 === row.charged2 ||
      ![row.atk, row.def, row.hp].every(iv => Number.isInteger(iv) && iv >= 0 && iv <= 15) ||
      !Number.isInteger(row.level * 2) || !Number.isFinite(row.level) ||
      row.level < 1 || row.level > MAX_LEVEL ||
      !Number.isInteger(row.cp) || row.cp < 10 || row.cp > CP_CAP) {
    throw Error("Invalid prepared Pokémon row");
  }

  const data = gameMaster.getPokemonById(row.species);
  if (!data || row.species.includes("_xl")) throw Error(`Unknown species: ${row.species}`);
  // The battle runner may change these forms before resolving damage or CMP.
  if (data.formChange || (data.originalFormId && data.originalFormId !== row.species) ||
      /^(aegislash|cramorant|minior)(?:_|$)/.test(row.species)) {
    throw Error(`Unsupported dynamic form: ${row.species}`);
  }
  if (row.level < (data.levelFloor ?? 1) || row.level > (data.levelCap ?? MAX_LEVEL)) {
    throw Error(`Level outside species bounds: ${row.species}`);
  }

  const pokemon = new Pokemon(row.species, index, battle);
  pokemon.ivs = {atk: row.atk, def: row.def, hp: row.hp};
  pokemon.isCustom = true;
  pokemon.setLevel(row.level, false);
  pokemon.initialize(false);
  if (pokemon.cp !== row.cp) {
    throw Error(`CP mismatch: ${row.species} ${pokemon.cp} != ${row.cp}`);
  }

  if (!pokemon.fastMovePool.some(move => move.moveId === row.fast) ||
      ![row.charged1, row.charged2].every(id => pokemon.chargedMovePool.some(move => move.moveId === id))) {
    throw Error(`Unsupported moveset: ${row.species}`);
  }
  pokemon.selectMove("fast", row.fast);
  pokemon.selectMove("charged", row.charged1, 0);
  pokemon.selectMove("charged", row.charged2, 1);
  const moves = [pokemon.fastMove, ...pokemon.chargedMoves.slice(0, 2)];
  if (moves[0]?.moveId !== row.fast || moves[0]?.category !== "fast" ||
      moves[1]?.moveId !== row.charged1 || moves[1]?.category !== "charged" ||
      moves[2]?.moveId !== row.charged2 || moves[2]?.category !== "charged" ||
      moves.some(move => move.formChange || !Number.isFinite(move.stab))) {
    throw Error(`Unsupported initialized moveset: ${row.species}`);
  }
  if (![pokemon.stats.atk, pokemon.stats.def].every(stat => Number.isFinite(stat) && stat > 0) ||
      !Number.isSafeInteger(pokemon.stats.hp) || pokemon.stats.hp < 10) {
    throw Error(`Invalid initialized stats: ${row.species}`);
  }
  return pokemon;
}

function setInitialBuffs(pokemon, buffs) {
  pokemon.setStartBuffs(buffs);
  pokemon.applyStatBuffs(pokemon.nativeStatBuffs);
}

function profileMatchup(candidate, opponent) {
  const damage = (attacker, defender, move) => DamageCalculator.damage(attacker, defender, move);
  // Battle's charged-action ordering uses raw stats.atk, independent of stat stages and shadow modifiers.
  const cmp = Math.sign(candidate.stats.atk - opponent.stats.atk);
  const profile = [candidate.stats.hp, cmp,
    damage(candidate, opponent, candidate.fastMove),
    damage(opponent, candidate, opponent.fastMove),
    damage(candidate, opponent, candidate.chargedMoves[0]),
    damage(candidate, opponent, candidate.chargedMoves[1]),
    damage(opponent, candidate, opponent.chargedMoves[0]),
    damage(opponent, candidate, opponent.chargedMoves[1])];
  if (!profile.slice(2).every(value => Number.isSafeInteger(value) && value > 0)) {
    throw Error("Invalid PvPoke damage profile");
  }
  return profile;
}

function profileBoundaries(request) {
  if (!request || typeof request.gamemaster_path !== "string" ||
      !path.isAbsolute(request.gamemaster_path) || request.gamemaster_path.length > 4096 ||
      !Array.isArray(request.candidates) || !request.candidates.length || request.candidates.length > MAX_CANDIDATES ||
      !Array.isArray(request.conditions) || !request.conditions.length || request.conditions.length > MAX_CONDITIONS) {
    throw Error("Invalid boundary profiler request");
  }

  loadMaster(request.gamemaster_path);
  const gameMaster = GameMaster.getInstance();
  const {maxBuffStages, buffDivisor} = gameMaster.data.settings;
  if (!Number.isSafeInteger(maxBuffStages) || maxBuffStages < 0 ||
      !Number.isFinite(buffDivisor) || buffDivisor <= 0) {
    throw Error("Invalid PvPoke buff settings");
  }

  // Keep the battle empty. Pokemon initializes its move STAB and type effectiveness
  // without an opponent. Damage is computed once per hit at the specified initial state.
  const battle = new Battle();
  battle.setCP(CP_CAP);
  const conditions = request.conditions.map(condition => {
    const buffs = condition?.buffs;
    if (!Array.isArray(buffs) || buffs.length !== 2 || !buffs.every(stages =>
      Array.isArray(stages) && stages.length === 2 && stages.every(stage =>
        Number.isInteger(stage) && Math.abs(stage) <= Math.min(maxBuffStages, 4)))) {
      throw Error("Invalid initial stat stages");
    }
    const opponent = preparePokemon(condition.opponent, 1, battle, gameMaster);
    setInitialBuffs(opponent, buffs[1]);
    return {opponent, candidateBuffs: buffs[0]};
  });

  return request.candidates.map(row => {
    const candidate = preparePokemon(row, 0, battle, gameMaster);
    return conditions.map(({opponent, candidateBuffs}) => {
      setInitialBuffs(candidate, candidateBuffs);
      return profileMatchup(candidate, opponent);
    });
  });
}

async function main() {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of process.stdin) {
    bytes += chunk.length;
    if (bytes > MAX_INPUT_BYTES) throw Error("Boundary profiler request is too large");
    chunks.push(chunk);
  }
  const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  process.stdout.write(JSON.stringify(profileBoundaries(request)) + "\n");
}

module.exports = {profileBoundaries};
if (require.main === module) {
  main().catch(error => {
    console.error(error.message);
    process.exitCode = 2;
  });
}
