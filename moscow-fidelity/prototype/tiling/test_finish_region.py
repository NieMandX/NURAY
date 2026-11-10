import gc
import time
import unittest
from types import SimpleNamespace
from finish_region import finish


class FinishMemoryScopeTest(unittest.TestCase):
    def test_validation_failure_restores_collector_state(self):
        original=gc.isenabled()
        try:
            for enabled in (True,False):
                (gc.enable if enabled else gc.disable)()
                def validate(*args):
                    self.assertFalse(gc.isenabled())
                    raise ValueError('real geometry rejection remains fatal')
                build=SimpleNamespace(overpass_profiles=[],road_model=SimpleNamespace(report={}),validate=validate)
                with self.assertRaisesRegex(ValueError,'real geometry rejection'):
                    finish(build,None,None,[],0,0,time.time())
                self.assertEqual(gc.isenabled(),enabled)
        finally:
            (gc.enable if original else gc.disable)()


if __name__=='__main__':unittest.main()
