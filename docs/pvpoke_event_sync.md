# PvPoke GameMaster / Great League recommendations: event-aware updates

This mechanism stages reviewable data changes, never production deployments.
It does not modify the saved opponent meta presets, teams, IV histories,
archives, Android exchange contract, or manually selected move sets.

## Sources and cadence

- Event dates: GO Calendar community day, event, GBL and season ICS feeds
  from https://gocalendar.info/. This is an unofficial Leek Duck / ScrapedDuck
  feed. Feed outages are reported, not treated as proof of no events.
- PvPoke sources: the upstream master commit pinned as a single SHA.
  GameMaster and Pokemon.js are obtained from the same revision.
  Great League recommended moves are obtained independently from the
  rankings/all/overall/rankings-1500.json snapshot.
- Calendar-only checks: 10:17 and 18:17 JST daily. PvPoke source is fetched
  only within one day before and two days after an event START, or on Monday
  (weekly fallback). Long seasons are NOT checked for their whole duration.
- No polling loops, automatic merge, or deployment. GitHub Actions cron can be
  delayed and the calendar can omit events. The weekly comparison is a fallback,
  not a guarantee of same-day updates.
- A manual workflow_dispatch with force=true can check immediately.

## Generated files

The script at tools/pvpoke_event_sync.py validates the upstream GameMaster
schema, move references, CPM array, GL ranking format and move legality.
Only two generated source files are staged:

- pvpoke_data_snapshot.py: SHA256 pins and approved upstream commit.
- data/pvpoke_recommended_moves.json: legal GL recommended movesets.

pvpoke_app_catalog.py prefers these new recommendations but falls back to the
existing pinned data if a recommended moveset is missing or illegal.
New legal moves do not automatically become recommended moves until PvPoke's
ranking actually recommends them.

The GitHub Action creates a Draft PR for meaningful changes after targeted
tests. It does NOT push to main. The repo may require enabling
Settings > Actions > General > Allow GitHub Actions to create and approve
pull requests. If unavailable, the Actions job fails rather than silently
deploying.

## Before accepting an automated proposal

1. Review upstream changes and confirm moves/availability against the
   announced event; compare official recommendations with GameMaster.
2. Run PvPoke battle-engine compatibility smoke tests with the new snapshot.
   Engine mechanics and moveset changes are not equivalent.
3. Test Kingambit / KOWTOW_CLEAVE when present, other representative species,
   preserved manual opponent moves, cache behavior and output contracts.
4. Merge and deploy only after explicit user approval; independently confirm
   the production catalog and recommended moves.

Useful local commands:

    python -m unittest discover -s tests -p 'test_pvpoke_event_sync.py' -v
    python tools/pvpoke_event_sync.py --force
    python tools/pvpoke_event_sync.py --force --apply

The CP1500 score-70 snapshot and saved calculation histories have independent
versioning; this change deliberately does not rewrite them. A full engine
update or score refresh needs a separate compatibility check.
