import tempfile
from pathlib import Path
import unittest
from canonical_validation_status import validation_passed


class CanonicalStatus(unittest.TestCase):
    def check(self,text):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json';path.write_text(text)
            return validation_passed(path)

    def test_root_verdict_and_last_duplicate(self):
        self.assertTrue(self.check('{"nested":{"passed":false},"passed":true,"large":[1,2,3]}'))
        self.assertTrue(self.check('{"passed":false,"passed":true}'))
        for text in ('{}','{"nested":{"passed":true}}','{"passed":false}',
                     '{"passed":true,"passed":false}','{"passed":"true"}','{"passed":null}'):
            self.assertFalse(self.check(text))

    def test_full_document_is_parsed_after_verdict(self):
        for text in ('{"passed":true,"later":[1,}', '{"passed":true} trailing',
                     '{"passed":true}{"passed":true}', '{"passed":true'):
            with self.assertRaises(ValueError):self.check(text)


if __name__=='__main__':unittest.main()
