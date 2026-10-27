import json,tempfile,unittest
from pathlib import Path
import shapely as sh
from landscape_reuse import array_records,changed_mask

class LandscapeReuse(unittest.TestCase):
 def test_stream_array_handles_unicode_nested_brackets_and_small_blocks(self):
  values=[dict(id='дерево',nested=[dict(text='], and escaped "text"')]),dict(id=2)]
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'city.json';p.write_text(json.dumps(dict(surfaces=values,other=[]),ensure_ascii=False,separators=(',',':')))
   self.assertEqual(list(array_records(p,'surfaces',7)),values)
 def test_changed_roles_invalidate_cell_even_if_green_is_same(self):
  green=sh.box(0,0,10,10);old=dict(raisedGeometry=sh.geometry.mapping(green),curbGeometry=sh.geometry.mapping(sh.Polygon()))
  layout=dict(raised=green,band=sh.Polygon(),railApron=sh.box(20,0,30,10),precision=1e-5)
  mask=changed_mask(old,layout)
  self.assertFalse(mask.intersects(sh.box(0,0,5,5)))
  self.assertTrue(mask.intersects(sh.box(19,4,21,5)))
  layout['band']=sh.box(0,0,10,.15)
  self.assertTrue(changed_mask(old,layout).intersects(sh.box(2,0,3,1)))

if __name__=='__main__':unittest.main()
