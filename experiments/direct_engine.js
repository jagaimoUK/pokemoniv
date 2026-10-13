#!/usr/bin/env node
/**
 * Experimental headless PvPoke Battle.js runner.
 * Never used by production. No browser, no DOM and no auto-fallback.
 * Input: JSON {sources:{gameMasterJs,pokemonJs,battleJs},gameMaster,candidate,opponent,shields}.
 * All Pokémon rows must contain prepared species/moves/level/IV/CP.
 */
"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
function run(payload) {
  const {sources, gameMaster, candidate, opponent, shields} = payload;
  if (!sources || !gameMaster || !candidate || !opponent || !Array.isArray(shields))
    throw Error("Missing required direct-engine input");
  const ctx = vm.createContext({
    console: {log(){},error(){}},
    host:"localhost",webRoot:"/",siteVersion:"local",
    settings:{gamemaster:"gamemaster"},
    $:{ajax(){}},
    window:{localStorage:{getItem(){return null;}}},
  });
  for (const [name,source] of [
    ["GameMaster.js",sources.gameMasterJs],
    ["Battle.js",sources.battleJs],
    ["Pokemon.js",sources.pokemonJs]
  ]) {
    if (typeof source !== "string" || source.length < 1000) throw Error("Invalid "+name);
    vm.runInContext(source,ctx,{filename:name,timeout:5000});
  }
  const gm = vm.runInContext("GameMaster.getInstance()",ctx);
  gm.data = gameMaster;
  gm.createSearchMaps();
  function makePoke(row, battle, index) {
    const id=row.species;
    const species=gm.getPokemonById(id);
    if(!species) throw Error("Unknown species: "+id);
    const p=vm.runInContext("new Pokemon("+JSON.stringify(id)+","+index+",__battle)",Object.assign(ctx,{__battle:battle}));
    p.ivs = {atk:Number(row.atk),def:Number(row.def),hp:Number(row.hp)};
    p.setLevel(Number(row.level),false);
    p.isCustom=true;
    p.initialize(false);
    for (const [type,id,slot] of [
      ["fast",row.fast,0],["charged",row.charged1,0],["charged",row.charged2,1]
    ]) {
      if(!id) throw Error("Move missing");
      p.selectMove(type,id,slot,true);
    }
    return p;
  }
  const battle = vm.runInContext("new Battle()",ctx);
  battle.setCP(1500);
  battle.setLevelCap(50);
  const a=makePoke(candidate,battle,0),b=makePoke(opponent,battle,1);
  a.setShields(Number(shields[0]));
  b.setShields(Number(shields[1]));
  battle.setNewPokemon(a,0,false);
  battle.setNewPokemon(b,1,false);
  battle.simulate();
  const rating=battle.getBattleRatings()[0];
  if(!Number.isFinite(rating)||rating<0||rating>1000)throw Error("Invalid Battle Rating "+rating);
  return {rating, shields, candidate: candidate.species, opponent:opponent.species};
}
if(require.main === module){
  try {process.stdout.write(JSON.stringify(run(JSON.parse(fs.readFileSync(0,"utf8"))))+"\n");}
  catch(e){process.stderr.write((e.stack||String(e))+"\n");process.exitCode=1;}
}
module.exports={run};
