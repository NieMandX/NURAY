import unittest
from source_objects import exterior_record

class Exterior(unittest.TestCase):
    def test_floorplan_building_is_an_outdoor_body(self):
        self.assertTrue(exterior_record({'db_sublayer':'Floor_plan_house','db_height':1142}))
        self.assertTrue(exterior_record({'db_sublayer':'Floor_plan_house_roof'}))
        self.assertFalse(exterior_record({'db_sublayer':'Floor','db_plan_id':'inside'}))
        self.assertFalse(exterior_record({'db_sublayer':'Floor_room'}))
        self.assertFalse(exterior_record({'db_sublayer':'Administrative_house','db_plan_id':'inside'}))
        self.assertFalse(exterior_record({'db_sublayer':'Traffic_light'}))
if __name__=='__main__':unittest.main()
