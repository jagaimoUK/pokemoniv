import unittest
from pvpoke_go_search import search_string
class GenderSearchTests(unittest.TestCase):
 def test_nidoran_gender_is_a_filter_not_a_literal_form(self):
  for name,sid,gender in [('Nidoran (Female)','nidoran_female','female'),('Nidoran♂','nidoran_male','male'),('Nidoran Female','nidoran_female','female')]:
   query=search_string(name,'0/15/15',False,sid)
   self.assertTrue(query.startswith('Nidoran&'+gender+'&'),query)
   self.assertNotIn('(',query);self.assertNotIn('♀',query)
 def test_other_gender_forms_and_shadow_keep_separate_filters(self):
  q=search_string('Meowstic (Female) (Shadow)','1/12/13',True,'meowstic_female_shadow')
  self.assertTrue(q.startswith('Meowstic&female&'))
  self.assertTrue(q.endswith('&shadow'))
  self.assertNotIn('!xxl',q)

 def test_flabebe_uses_english_name_not_dex_number(self):
  self.assertEqual(search_string('Flabébé','0/15/15',False,'flabebe'), 'Flabébé&0attack&4defense&4hp')

 def test_low_score_queries_also_keep_gender_as_a_filter(self):
  from pvpoke_score_search import _search_term
  value,error=_search_term({'name':'ニドラン♀','dex':29},{},'Nidoran♀')
  self.assertIsNone(error)
  self.assertEqual(value,('Nidoran',('female','!shadow')))
