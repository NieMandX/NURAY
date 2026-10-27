import io,json,unittest
from registry_validation import compare_json,matches_serialized


class RegistryValidation(unittest.TestCase):
    def test_bounded_byte_fast_path(self):
        actual={'features':[{'id':i,'name':'Берег'} for i in range(10000)],'meta':{'passed':True}}
        raw=json.dumps(actual,ensure_ascii=False,separators=(',',':')).encode()
        self.assertTrue(matches_serialized(io.BytesIO(raw),{**actual,'features':iter(actual['features'])}))
        self.assertFalse(matches_serialized(io.BytesIO(raw.replace(b'100,',b'101,',1)),actual))
        self.assertFalse(matches_serialized(io.BytesIO(raw+b' '),actual))

    def test_order_independent_and_incremental_arrays(self):
        actual={'surfaces':[{'geometry':[[1.2,3],[4,5]],'owner':'road'} for _ in range(1000)],'passed':True,'missing':None}
        expected={'missing':None,'passed':True,'surfaces':({'owner':'road','geometry':[[1.2,3],[4,5]]} for _ in range(1000))}
        compare_json(io.BytesIO(json.dumps(actual).encode()),expected)

    def test_rejects_corruption_in_previously_uncompared_geometry(self):
        expected={'surfaces':[{'geometry':[[1,2]],'material':3}]}
        for actual in [
            {'surfaces':[{'geometry':[[1,2.1]],'material':3}]},
            {'surfaces':[{'geometry':[[1,2]],'material':4}]},
            {'surfaces':[]},
            {'surfaces':expected['surfaces']*2},
            {'surfaces':expected['surfaces'],'unknown':1},
            {},
        ]:
            with self.subTest(actual=actual),self.assertRaises(AssertionError):
                compare_json(io.BytesIO(json.dumps(actual).encode()),expected)
        with self.assertRaises(AssertionError):compare_json(io.BytesIO(b'{"x":1,"x":1}'),{'x':1})
        with self.assertRaises(AssertionError):compare_json(io.BytesIO(b'{"x":1}'),{'x':True})


if __name__=='__main__':unittest.main()
