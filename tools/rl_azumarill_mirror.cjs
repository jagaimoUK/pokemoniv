"use strict";

const {chooseTeamCpu} = require("../pvpoke_rl_team_native.js");
const {
  bankedChargeAction, compareChargeFork, publicChargeState, verifiedNativeReward,
} = require("./rl_charge_branches.cjs");
const {CHARGE_MS, createPublicReplayRecorder} = require("./rl_public_replay.cjs");

function runMirrorArm(session, startingOpponentShields, openingAction, choice) {
  let response = session.response();
  const opponentLead = response.observation?.opponent.active_species;
  let openingChosen = false;
  let mirrorSeen = false;
  let iceBeamLegal = false;
  let chargeFork = null;
  const replay = createPublicReplayRecorder();

  for (let steps = 0; response.observation && steps < 2000; steps++) {
    const view = response.observation;
    const slot = view.own.active_slot;
    const active = view.own.team[slot];
    let action = chooseTeamCpu(view);

    if (!openingChosen && view.phase === "turn" && slot === 0) {
      action = bankedChargeAction(view, startingOpponentShields);
      if (action === "charge_0") {
        action = openingAction;
        openingChosen = true;
      }
    } else if (openingChosen && !chargeFork && view.phase === "turn" &&
        active.species === "azumarill" && view.opponent.active_species === "azumarill") {
      mirrorSeen = true;
      const iceSlot = active.charged_moves.findIndex(move => move.move_id === "ICE_BEAM");
      if (iceSlot === -1) throw Error("Mirror fixture has no Ice Beam");
      const iceBeam = "charge_" + iceSlot;
      // Engine legal switches are enumerated in own team slot order.
      const switchAction = view.legal_actions.find(candidate => candidate.startsWith("switch_"));
      if (view.legal_actions.includes(iceBeam)) {
        iceBeamLegal = true;
        if (switchAction) {
          chargeFork = {view, audit: session.privateReplay(), baselineAction: iceBeam, switchAction};
          action = choice === "immediate" ? iceBeam : choice;
        }
      }
    }
    response = session.step([action, chooseTeamCpu(session.observe(1))]);
    replay.onStep(view, response);
  }

  if (response.observation) throw Error("Mirror study exceeded its step budget");
  if (!chargeFork) {
    let excluded = "no_simultaneous_switch_in_mirror";
    if (!openingChosen) excluded = "opening_not_reached";
    else if (!mirrorSeen) excluded = "mirror_not_reached";
    else if (!iceBeamLegal) excluded = "ice_beam_never_legal_in_mirror";
    return {excluded, outcome: response.info.outcome};
  }
  const audit = session.privateReplay();
  return {chargeFork, audit, opponentLead, replay: replay.summarize(audit.events),
    reward: verifiedNativeReward(response), outcome: response.info.outcome};
}

function summarizeArm(rolled, ownLead, opponentLead, switchTo) {
  const {audit, view} = rolled.chargeFork;
  const forkSeq = audit.events.length;
  const active = {self: ownLead, opponent: opponentLead};
  let mirrorCharges = 0;
  let forkActionResolved = false;
  for (const event of rolled.replay.events) {
    if (event.kind === "switch") active[event.side] = event.species;
    if (event.seq <= forkSeq) continue;
    if (event.kind === "charged" && active.self === "azumarill" && active.opponent === "azumarill") {
      mirrorCharges++;
    }
    if (event.turn !== view.turn || event.side !== "self") continue;
    if (switchTo === null) {
      if (event.kind === "charged" && event.species === "azumarill" && event.move_id === "ICE_BEAM") {
        forkActionResolved = true;
      }
    } else if (event.kind === "switch" && !event.forced &&
        event.previous_species === "azumarill" && event.species === switchTo) {
      forkActionResolved = true;
    }
  }
  return {reward: rolled.reward, outcome: rolled.outcome, action_resolved: forkActionResolved,
    elapsed_ms: rolled.replay.elapsed_ms, mirror_charges_after_fork: mirrorCharges,
    mirror_charge_ms_after_fork: mirrorCharges * CHARGE_MS, replay: rolled.replay};
}

function compareMirrorForks(newSession, startingOpponentShields, lead) {
  return ["charge_0", "charge_1"].map((openingAction, slot) => {
    const {immediate, alternatives} = compareChargeFork(
      choice => runMirrorArm(newSession(), startingOpponentShields, openingAction, choice),
      fork => [fork.switchAction],
    );
    const openingMove = slot === 0 ? lead.charged1 : lead.charged2;
    const {chargeFork} = immediate;
    if (!chargeFork) {
      return {opening_move: openingMove, excluded: immediate.excluded, outcome: immediate.outcome};
    }
    const {view, switchAction, audit} = chargeFork;
    const switchTo = view.own.team[Number(switchAction.slice("switch_".length))].species;
    const {opponentLead} = immediate;
    return {opening_move: openingMove, public_state: publicChargeState(view),
      own_shields: view.own.shields, switch_to: switchTo, after_event_seq: audit.events.length,
      ice_beam: summarizeArm(immediate, lead.species, opponentLead, null),
      switch: summarizeArm(alternatives[switchAction], lead.species, opponentLead, switchTo)};
  });
}

module.exports = {compareMirrorForks};
