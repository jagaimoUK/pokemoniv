// Source: https://github.com/pvpoke/pvpoke/blob/d98f52174e01f8f67414bc6973599788d098c10e/src/js/interface/PokeMultiSelect.js
// PvPoke PokeMultiSelect.quickFillCSV, MIT (vendor/pvpoke/LICENSE).
this.quickFillCSV = function(csv){

		var arr = csv.split('\n');

		pokemonList = [];

		var cp = battle.getCP();

		for(var i = 0; i < arr.length; i++){
			if(pokemonList.length >= maxPokemonCount){
				break;
			}

			var poke = arr[i].split(',');
			var pokeSettings = poke[0].split('-'); // Get the Pokemon ID and shadow type

			var pokemon = new Pokemon(pokeSettings[0].toLowerCase(), 1, battle);

			if(pokemon?.initialize){
				pokemon.initialize(cp);
				if(pokeSettings[1]){
					pokemon.setShadowType(pokeSettings[1]);
				}

				let ivStartIndex = 4; // First part of array is of variable length, so we need to identify where the level and iv numbers begin
				let moveNameRegex = new RegExp("^([a-zA-Z_]*)$");

				if(poke.length > 1){
					// Set moves

					pokemon.selectMove("fast", poke[1]);
					pokemon.selectMove("charged", poke[2], 0);
					pokemon.selectMove("charged", poke[3], 1);

					// Set first slot to none if both are none

					if((poke[2] == 'none')&&(poke[3] == 'none')){
						pokemon.selectMove("charged", poke[3], 0);
					}

					// Set third charged move, if any
					if(poke.length > 4 && moveNameRegex.test(poke[4])){
						ivStartIndex++;
						pokemon.selectMove("extra-charged", poke[4], 2);
					}

					

				} else{
					// Select recommended moves
					pokemon.selectRecommendedMoveset();
				}
				// Set any custom levels or ivs

				if(poke.length > 4){
					pokemon.isCustom = true;

					const level = parseFloat(poke[ivStartIndex]);
					const atk = parseFloat(poke[ivStartIndex+1]);
					const def = parseFloat(poke[ivStartIndex+2]);
					const hp = parseFloat(poke[ivStartIndex+3]);

					// Don't set stats to be NaN
					if (Number.isNaN(level) || Number.isNaN(atk) || Number.isNaN(def) || Number.isNaN(hp)) {
						// Ignoring the alert here since 3rd party imports may not have IVs/Level
						// alert("Line " + (i+1) + " has invalid stats: \"" + poke + "\".");
					} else {
						pokemon.setLevel(level);
						pokemon.setIV("atk", atk);
						pokemon.setIV("def", def);
						pokemon.setIV("hp", hp);
					}
				}

				pokemonList.push(pokemon);
			}
		}

		self.updateListDisplay();
	}
