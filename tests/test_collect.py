import importlib.util
import pathlib
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'collect.py'
spec = importlib.util.spec_from_file_location('collect', MODULE)
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


class CollectorTests(unittest.TestCase):
    def test_valid_offer_lead(self):
        value = collect.classify('郑州霸王茶姬奶茶满减券活动', '', {'region': '全国', 'platform': '公开资讯'})
        self.assertEqual(value['region'], '郑州')
        self.assertEqual(value['brand'], '霸王茶姬')
        self.assertEqual(value['status'] if 'status' in value else 'unverified', 'unverified')

    def test_no_coupon_keyword(self):
        self.assertIsNone(collect.classify('郑州奶茶新品上市', '', {'region': '郑州'}))

    def test_reject_non_https(self):
        self.assertIsNone(collect.normalize_link('javascript:alert(1)'))
        self.assertIsNone(collect.normalize_link('http://example.org/a'))

    def test_strip_fragment(self):
        self.assertEqual(collect.normalize_link('https://example.org/a#section'), 'https://example.org/a')


if __name__ == '__main__':
    unittest.main()
