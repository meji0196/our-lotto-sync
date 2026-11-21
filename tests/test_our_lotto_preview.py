"""Offline regression tests for structured Our Lotto previews with Pilio fallback."""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPT_DIR))
import our_lotto_preview as sync

TIME = datetime(2026, 11, 21, 21, 30, tzinfo=timezone(timedelta(hours=8)))
DATE = '2026-11-21'


def record(game, numbers=None, special=None, source='third', *, date=DATE,
           conflict=False, period=''):
    example = {
        'daily': [7, 19, 20, 28, 32],
        'lotto': [1, 2, 4, 12, 16, 38],
        'power': [1, 12, 13, 18, 30, 33],
        'three': [0, 5, 4],
        'four': [0, 7, 2, 5],
    }
    if numbers is None:
        numbers = example[game]
    if special is None and game in ('lotto', 'power'):
        special = 44 if game == 'lotto' else 3
    if source == 'official' and not period:
        period = '115000281'
    url = ('https://api.taiwanlottery.com/TLCAPIWeB/Lottery/3DResult'
           if source == 'official' else 'https://www.pilio.idv.tw/')
    return {'period': period, 'date': date, 'numbers': numbers, 'appear': numbers,
            'special': special, 'source': source,
            'sourceUrl': url, 'conflict': conflict}


def response(game, **options):
    return {'game': game, 'rows': [record(game, **options)],
            'checkedAt': '2026-11-21T21:15:00+08:00', 'stale': False}


def no_pilio(page):
    raise ConnectionError('Pilio offline: ' + page)


class PrimaryPreviewTests(unittest.TestCase):
    def test_our_latest_539(self):
        row = sync.parse_our_results('539', response('daily'), TIME.date())
        self.assertEqual(row['numbers'], [7, 19, 20, 28, 32])
        self.assertEqual(row['source'], 'our-lotto')
        self.assertEqual(row['upstreamSource'], 'third')
        self.assertIs(row['verified'], False)

    def test_stars_preserve_positions_and_zeros(self):
        self.assertEqual(sync.parse_our_results('3star', response('three'), TIME.date())['numbers'], [0, 5, 4])
        self.assertEqual(sync.parse_our_results('4star', response('four'), TIME.date())['numbers'], [0, 7, 2, 5])

    def test_power_second_zone_and_lotto_special(self):
        self.assertEqual(sync.parse_our_results('power', response('power'), TIME.date())['special'], 3)
        self.assertEqual(sync.parse_our_results('lotto649', response('lotto'), TIME.date())['special'], 44)

    def test_official_source_still_unverified_in_preview_feed(self):
        row = sync.parse_our_results('539', response('daily', source='official'), TIME.date())
        self.assertEqual(row['upstreamSource'], 'official')
        self.assertIs(row['verified'], False)

    def test_reject_invalid_numbers(self):
        bad = ([7, 7, 20, 28, 32], [7, 19, 20, 28, 40], [7, 19, 20, 28], [7, 19, 20, 28, True])
        for nums in bad:
            with self.subTest(nums=nums), self.assertRaises(ValueError):
                sync.parse_our_results('539', response('daily', numbers=nums), TIME.date())

    def test_bad_second_zone_and_lotto_repeat(self):
        with self.assertRaises(ValueError):
            sync.parse_our_results('power', response('power', special=9), TIME.date())
        with self.assertRaises(ValueError):
            sync.parse_our_results('lotto649', response('lotto', special=16), TIME.date())

    def test_conflict_is_quarantined(self):
        with self.assertRaises(sync.SourceConflict):
            sync.parse_our_results('539', response('daily', conflict=True), TIME.date())

    def test_claimed_official_source_cannot_point_to_pilio(self):
        data = response('daily', source='official')
        data['rows'][0]['sourceUrl'] = 'https://www.pilio.idv.tw/'
        with self.assertRaisesRegex(ValueError, 'must point to Taiwan Lottery'):
            sync.parse_our_results('539', data, TIME.date())

    def test_missing_stale_flag_is_rejected(self):
        data = response('daily'); data.pop('stale')
        with self.assertRaisesRegex(ValueError, 'stale'):
            sync.parse_our_results('539', data, TIME.date())

    def test_missing_conflict_metadata_fails_closed(self):
        data = response('daily')
        data['rows'][0].pop('conflict')
        with self.assertRaises(sync.SourceConflict):
            sync.parse_our_results('539', data, TIME.date())

    def test_stale_future_and_game_mismatch(self):
        stale = response('daily'); stale['stale'] = True
        with self.assertRaisesRegex(ValueError, 'stale'):
            sync.parse_our_results('539', stale, TIME.date())
        with self.assertRaisesRegex(ValueError, 'future'):
            sync.parse_our_results('539', response('daily', date='2026-11-22'), TIME.date())
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            sync.parse_our_results('539', response('power'), TIME.date())

    def test_out_of_order_not_trusted(self):
        data = response('daily', date='2026-11-20')
        data['rows'].append(record('daily', date='2026-11-21'))
        with self.assertRaisesRegex(ValueError, 'not sorted'):
            sync.parse_our_results('539', data, TIME.date())

    def test_primary_success_does_not_call_pilio(self):
        calls = []
        def ours(game):
            calls.append(game)
            return response(game)
        def pilio(_):
            raise AssertionError('should not visit Pilio for good primary records')
        rows = sync.build_feed(TIME, {}, fetch_our=ours, fetch_pilio=pilio)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(x['source'] == 'our-lotto' for x in rows.values()))

    def test_pilio_fallback_on_primary_failure(self):
        def offline(_):
            raise ConnectionError('primary offline')
        def pilio(page):
            if page == 'main_lto34.asp':
                numbers = [0, 7, 2, 5, 5, 7, 4]
            elif page == 'main_lto539.asp':
                numbers = [7, 19, 20, 28, 32]
            elif page == 'main_ltobig.asp':
                numbers = [1, 2, 4, 12, 16, 38, 44]
            else:
                numbers = [1, 12, 13, 18, 30, 33, 3]
            return ('<h2>2026/11/21_(六) 最新開獎號碼</h2>'
                    + ''.join('<span>' + str(x) + '</span>' for x in numbers)
                    + '<p>每週一至六開獎</p>')
        rows = sync.build_feed(TIME, {}, fetch_our=offline, fetch_pilio=pilio)
        self.assertEqual(rows['3star']['numbers'], [0, 7, 2])
        self.assertEqual(rows['4star']['numbers'], [5, 5, 7, 4])
        self.assertEqual(rows['539']['source'], 'pilio')

    def test_conflict_does_not_fallback_to_same_upstream(self):
        called = []
        def ours(game):
            if game == 'daily':
                return response(game, conflict=True)
            raise RuntimeError('other site offline')
        def pilio(page):
            called.append(page)
            raise RuntimeError('Pilio offline')
        quarantined = set()
        rows = sync.build_feed(TIME, {}, fetch_our=ours, fetch_pilio=pilio, quarantined=quarantined)
        self.assertIn('539', quarantined)
        self.assertNotIn('539', rows)
        self.assertNotIn('main_lto539.asp', called)

    def test_star_old_cache_is_not_reused_if_both_sources_fail(self):
        old = {
            '3star': {'date': DATE, 'numbers': [5, 7, 4], 'special': None, 'source': 'pilio', 'verified': False},
            '539': {'date': DATE, 'numbers': [7, 19, 20, 28, 32], 'special': None, 'source': 'pilio', 'verified': False},
        }
        def offline(_):
            raise OSError('offline')
        rows = sync.build_feed(TIME, old, fetch_our=offline, fetch_pilio=offline)
        self.assertEqual(rows['539'], old['539'])
        self.assertNotIn('3star', rows)


if __name__ == '__main__':
    unittest.main()
