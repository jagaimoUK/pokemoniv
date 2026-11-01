"""Local frozen-engine comparison; no external PvPoke calls. Run with PYTHONPATH=.:tests."""
import json, subprocess, tempfile, threading, time, types, statistics
from pathlib import Path
from unittest.mock import patch
import pvpoke_meta_variants as current
from pvpoke_direct_backend import DirectMatrixClient
from test_party_strategy import ROWS, GM, SPECIES, CPMS, engine
old=types.ModuleType('old_variants')
exec(subprocess.check_output(['git','show','083f711:pvpoke_meta_variants.py'],text=True),old.__dict__)
source=''.join(','.join(r[k] for k in engine.HEADER[:4])+'\n' for r in ROWS)
results=[]
for _ in range(3):
 for label,module in [('previous',old),('minimal',current)]:
  with tempfile.TemporaryDirectory() as tmp:
   work=Path(tmp);(work/'gamemaster.json').write_text(json.dumps(GM))
   with patch.object(engine,'DATA',work):
    client=DirectMatrixClient(gamemaster=work/'gamemaster.json',log_dir=work)
    tick=time.monotonic()
    try:rows,evidence,added=module.evaluate({'source_csv':source},client,SPECIES,CPMS,threading.Lock(),{'state':'idle'},lambda _:None)
    finally:client.close()
    results.append(dict(case=label,seconds=round(time.monotonic()-tick,4),added=added,profiles=sum(e['tested'] for e in evidence)))
print(json.dumps({'samples':results,'median_seconds':{key:statistics.median(r['seconds'] for r in results if r['case']==key) for key in ('previous','minimal')}},indent=2))
