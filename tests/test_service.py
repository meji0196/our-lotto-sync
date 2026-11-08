import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from core import ROOT, BASE_WEEKDAYS, source_is_official, valid_iso, load_approved_config, load_auto_config, validate_promotions
from monitor import extract_relevant_links, strict_parse_spring_extra, OfficialHTML
from publish import build
from unittest.mock import patch
import monitor


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ROOT / 'tests' / 'fixtures'

    def test_initial_manually_verified_dates(self):
        cfg = load_approved_config(ROOT / 'config' / 'approved-calendar.json')
        self.assertEqual(len(cfg['lotto649']['addedDates']), 14)
        self.assertEqual(len(cfg['539']['addedDates']), 3)
        self.assertEqual(len(cfg['power']['addedDates']), 0)

    def test_auto_approval_file_is_valid(self):
        self.assertEqual(load_auto_config(ROOT / 'state' / 'auto-approved.json')['lotto649'], set())
        self.assertEqual(validate_promotions(ROOT / 'config' / 'approved-promotions.json'), [])

    def test_notice_discovery_filters_unrelated_and_wrong_hosts(self):
        html = (self.fixture / 'official-index-2026.html').read_text(encoding='utf-8')
        links = extract_relevant_links(html, 'https://lotto.ctbcbank.com/news115.htm')
        self.assertEqual(list(links), ['https://lotto.ctbcbank.com/news1150908.htm'])

    def test_official_spring_2026_dates(self):
        page = OfficialHTML()
        page.feed((self.fixture / 'official-spring-2026.html').read_text(encoding='utf-8'))
        result = strict_parse_spring_extra(page.text(), '公告115年春節加碼期間增加開獎日相關事宜', 'https://lotto.ctbcbank.com/news1141212.htm')
        self.assertEqual(len(result['games']['lotto649']), 14)
        self.assertEqual(len(result['games']['539']), 3)
        self.assertEqual(result['games']['lotto649'][0], '2026-02-12')
        self.assertEqual(result['games']['lotto649'][-1], '2026-03-02')

    def test_modified_or_partial_official_notice_must_not_auto_publish(self):
        page = OfficialHTML()
        page.feed((self.fixture / 'official-spring-2026.html').read_text(encoding='utf-8'))
        text = page.text()
        with self.assertRaises(ValueError):
            strict_parse_spring_extra(text.replace('各增加14個開獎日', '各增加15個開獎日'), '公告115年春節加碼期間增加開獎日相關事宜', 'https://lotto.ctbcbank.com/news1141212.htm')
        with self.assertRaises(ValueError):
            strict_parse_spring_extra(text.replace('115年2月12日（四）', '115年2月12日（五）'), '公告115年春節加碼期間增加開獎日相關事宜', 'https://lotto.ctbcbank.com/news1141212.htm')
        with self.assertRaises(ValueError):
            strict_parse_spring_extra(text, '公告115年春節加碼期間增加開獎日相關事宜', 'https://evil.example.com/news1141212.htm')

    def test_monitor_only_auto_publishes_strict_official_schedule(self):
        detail = (self.fixture / 'official-spring-2026.html').read_text(encoding='utf-8')
        listing = '<html><a href="news1141212.htm">公告115年春節加碼期間增加開獎日相關事宜</a></html>'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config').mkdir()
            (root / 'state').mkdir()
            (root / 'config' / 'settings.json').write_text(json.dumps({'autoApproveStrictSpringExtraDates': True}), encoding='utf-8')
            (root / 'state' / 'seen-notices.json').write_text(json.dumps({'schemaVersion': 1, 'urls': []}), encoding='utf-8')
            (root / 'state' / 'pending-notices.json').write_text(json.dumps({'schemaVersion': 1, 'notices': []}), encoding='utf-8')
            (root / 'state' / 'auto-approved.json').write_text(json.dumps({'schemaVersion': 1, 'records': []}), encoding='utf-8')
            def mock_fetch(url):
                return listing if url.endswith('news114.htm') else detail
            with patch.object(monitor, 'ROOT', root), patch.object(monitor, 'roc_news_indexes', return_value=['https://lotto.ctbcbank.com/news114.htm']), patch.object(monitor, 'fetch_official', side_effect=mock_fetch):
                accepted, pending = monitor.scan()
            self.assertEqual((accepted, pending), (1, 0))
            record = json.loads((root / 'state' / 'auto-approved.json').read_text(encoding='utf-8'))['records'][0]
            self.assertEqual(len(record['games']['lotto649']), 14)
            self.assertEqual(len(record['games']['539']), 3)

    def test_official_url_is_constrained(self):
        self.assertTrue(source_is_official('https://lotto.ctbcbank.com/news1141212.htm'))
        self.assertFalse(source_is_official('https://lotto.ctbcbank.com.evil.org/news1141212.htm'))
        self.assertFalse(source_is_official('http://lotto.ctbcbank.com/news1141212.htm'))
        self.assertFalse(source_is_official('https://lotto.ctbcbank.com/../news1141212.htm'))

    def test_publish_file_format_compatible_with_existing_app(self):
        build()
        data = json.loads((ROOT / 'docs' / 'aoer-schedule.json').read_text(encoding='utf-8'))
        self.assertEqual(data['schemaVersion'], 1)
        self.assertEqual(set(data['games']), set(BASE_WEEKDAYS))
        self.assertEqual(len(data['games']['lotto649']['addedDates']), 14)
        self.assertTrue(data['issuedAt'].endswith('Z'))
        for game, cfg in data['games'].items():
            for iso in cfg['addedDates'] + cfg['cancelledDates']:
                self.assertTrue(valid_iso(iso))
                self.assertEqual(len(iso), 10)


if __name__ == '__main__':
    unittest.main()
