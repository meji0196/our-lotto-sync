"""Pilio preview parser regressions (no network access required)."""
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'pilio_preview.py'
spec = importlib.util.spec_from_file_location('pilio_preview', SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
TODAY = datetime(2026, 11, 10, tzinfo=timezone(timedelta(hours=8)))


def sample(balls, day='2026/11/09'):
    return '<html><body><h1>34星彩專區</h1><h2>' + day + '_(一) 最新開獎號碼</h2>' + ''.join(f'<span>{n}</span>' for n in balls) + '<p>每週一至六晚間開獎</p><div>2026/11/09 - 4星彩獎金分配表 50,000 2 500 873</div></body></html>'


class PreviewTests(unittest.TestCase):
    def test_real_2026_11_09_stars_correctly_split(self):
        html = sample([0, 7, 2, 5, 5, 7, 4])
        self.assertEqual(module.parse_html('3star', html, TODAY.date())['numbers'], [0, 7, 2])
        self.assertEqual(module.parse_html('4star', html, TODAY.date())['numbers'], [5, 5, 7, 4])

    def test_leading_zero_and_repeated_digits(self):
        html = sample([0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(module.parse_html('3star', html, TODAY.date())['numbers'], [0, 0, 0])
        self.assertEqual(module.parse_html('4star', html, TODAY.date())['numbers'], [0, 0, 0, 0])

    def test_wrong_digit_count_is_rejected(self):
        for numbers in ([0, 7, 2, 5, 5, 7], [0, 7, 2, 5, 5, 7, 4, 8]):
            for game in ('3star', '4star'):
                with self.assertRaisesRegex(ValueError, 'exactly 7'):
                    module.parse_html(game, sample(numbers), TODAY.date())

    def test_bad_digit_and_stale_date_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly 7'):
            module.parse_html('3star', sample([0, 7, 2, 5, 5, 7, 10]), TODAY.date())
        with self.assertRaisesRegex(ValueError, 'stale or future'):
            module.parse_html('4star', sample([0, 7, 2, 5, 5, 7, 4], '2026/11/05'), TODAY.date())

    def test_invalid_stars_not_carried_forward_from_prior_version(self):
        bad_old = {'3star': {'date': '2026-11-09', 'numbers': [5, 7, 4], 'source': 'pilio', 'verified': False}, '4star': {'date': '2026-11-09', 'numbers': [0, 7, 2, 5], 'source': 'pilio', 'verified': False}}
        def broken_page(_page):
            return sample([0, 7, 2])
        self.assertEqual(module.build_feed(TODAY, bad_old, fetch=broken_page), {})

    def test_shared_page_fetched_once(self):
        calls = []
        def fake_fetch(page):
            calls.append(page)
            if page == 'main_lto34.asp':
                return sample([0, 7, 2, 5, 5, 7, 4])
            raise OSError('network unavailable')
        rows = module.build_feed(TODAY, {}, fetch=fake_fetch)
        self.assertEqual(rows['3star']['numbers'], [0, 7, 2])
        self.assertEqual(rows['4star']['numbers'], [5, 5, 7, 4])
        self.assertEqual(calls.count('main_lto34.asp'), 1)

    def test_nonstar_validation(self):
        def make(n):
            return '<h2>2026/11/09_(一) 最新開獎號碼</h2>' + ''.join(f'<i>{v:02}</i>' for v in n) + '<p>每週一至六開獎</p>'
        self.assertEqual(module.parse_html('539', make([7, 9, 28, 30, 33]), TODAY.date())['numbers'], [7,9,28,30,33])
        with self.assertRaisesRegex(ValueError, 'repeated'):
            module.parse_html('539', make([7, 9, 28, 30, 30]), TODAY.date())


if __name__ == '__main__':
    unittest.main()
