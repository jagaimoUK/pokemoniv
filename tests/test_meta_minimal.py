import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import pvpoke_meta_variants as variants
from pvpoke_direct_backend import DirectMatrixClient
from test_party_strategy import ROWS, GM, SPECIES, CPMS, engine


class MinimalMetaTests(unittest.TestCase):
    def test_shortlist_preserves_manual_and_bounds_extras(self):
        row=tuple(ROWS[0][k] for k in engine.HEADER[:4])
        moves={m['moveId']:m for m in GM['moves']}
        result=variants.shortlist([row],SPECIES[row[0]],moves)
        self.assertEqual(result[0],row)
        self.assertLessEqual(len(result),7)
        self.assertEqual(len({variants.row_key(r) for r in result}),len(result))
        self.assertEqual(variants.shortlist([row],SPECIES[row[0]],{}),[row])

    def test_real_engine_preserves_input_and_limits_work(self):
        before=copy.deepcopy(ROWS)
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);(work/'gamemaster.json').write_text(json.dumps(GM))
            source=''.join(','.join(r[k] for k in engine.HEADER[:4])+'\n' for r in ROWS)
            job={'source_csv':source}
            with patch.object(engine,'DATA',work):
                client=DirectMatrixClient(gamemaster=work/'gamemaster.json',log_dir=work)
                try:
                    rows,evidence,added=variants.evaluate(job,client,SPECIES,CPMS,
                        threading.Lock(),{'state':'idle'},lambda _:None)
                finally:client.close()
            self.assertEqual(rows[:6],[tuple(r[k] for k in engine.HEADER[:4]) for r in ROWS])
            self.assertLessEqual(added,6)
            self.assertTrue(all(e['tested']<=7 for e in evidence))
            self.assertTrue(all(len(c['new_species'])>=2 for e in evidence for c in e['chosen']))
        self.assertEqual(ROWS,before)
