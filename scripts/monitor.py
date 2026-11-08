#!/usr/bin/env python3
"""Conservatively monitor official lottery notices.

Only a narrowly recognised, fully validated spring extra-draw table may be
approved automatically. Promotions and all other date changes require review.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from core import ROOT, BASE_WEEKDAYS, source_is_official, valid_iso, read_json, write_json

OFFICIAL = 'https://lotto.ctbcbank.com/'
ROW_RE = re.compile(r'(\d{3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[（(]\s*([日一二三四五六])\s*[）)]\s*第\s*(\d{9})\s*期')
WEEKDAY_CHARS = '日一二三四五六'
RELEVANT = (
    r'春節.*(加碼|開獎日)',
    r'中秋.*加碼',
    r'端午.*加碼',
    r'電腦型彩券.*(加碼|促銷活動|新增開獎|增加開獎|調整開獎)',
    r'(增加|新增|調整|變更|取消|停止).*開獎日',
    r'大樂透.*(促銷|加碼)',
)


class OfficialHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self.data_items = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            self.active = {'href': dict(attrs).get('href', ''), 'chunks': []}
        elif tag.lower() in ('br', 'hr', 'p', 'tr', 'td', 'li'):
            self.data_items.append(' ')

    def handle_data(self, data):
        self.data_items.append(data)
        if self.active is not None:
            self.active['chunks'].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'a' and self.active is not None:
            self.anchors.append((self.active['href'], ' '.join(self.active['chunks']).strip()))
            self.active = None
        elif tag.lower() in ('p', 'tr', 'td', 'li'):
            self.data_items.append(' ')

    def text(self):
        return re.sub(r'\s+', ' ', unescape(' '.join(self.data_items))).strip()


def decode_html(data: bytes, charset: str | None):
    # Some old official news pages declare a legacy or fallback HTTP charset.
    # Check the HTML meta tag first and prefer Chinese-capable encodings.
    meta = re.search(rb'<meta[^>]+charset\s*=\s*["\']?([A-Za-z0-9_-]+)', data[:4096], re.I)
    meta_charset = meta.group(1).decode('ascii', errors='ignore') if meta else None
    declared = charset if charset and charset.lower() not in ('iso-8859-1', 'latin-1') else None
    for encoding in [meta_charset, declared, 'utf-8-sig', 'cp950', 'big5']:
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeError, LookupError):
            continue
    raise ValueError('official page encoding could not be decoded')


def fetch_official(url: str):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'lotto.ctbcbank.com' or parsed.port is not None:
        raise ValueError('Refusing request to non-official URL')
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 (OurLottoCalendarMonitor/1.0; read-only official announcement checker)', 'Accept': 'text/html'})
    with urlopen(request, timeout=20) as response:
        if urlparse(response.geturl()).hostname != 'lotto.ctbcbank.com':
            raise ValueError('official site redirected outside its HTTPS domain')
        if response.status != 200:
            raise RuntimeError('upstream status ' + str(response.status))
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('official page too large')
        charset = response.headers.get_content_charset()
        return decode_html(body, charset)


def extract_relevant_links(html: str, base_url: str):
    p = OfficialHTML()
    p.feed(html)
    notice = {}
    for href, title in p.anchors:
        target = urljoin(base_url, href)
        title = re.sub(r'\s+', ' ', title).strip()
        if source_is_official(target) and len(title) <= 250 and any(re.search(q, title) for q in RELEVANT):
            notice[target] = title
    return notice


def row_list(block: str, base: date, games: list[str]):
    count_re = re.search(r'各增加\s*(\d+)\s*個開獎日', block)
    if not count_re:
        raise ValueError('official addition count missing')
    expected = int(count_re.group(1))
    if not 1 <= expected <= 40:
        raise ValueError('official addition count outside supported range')
    rows = ROW_RE.findall(block)
    if len(rows) != expected:
        raise ValueError(f'official added date count inconsistent: expected {expected}, parsed {len(rows)}')
    dates = []
    periods = set()
    for roc, month, day, wch, period in rows:
        year = int(roc) + 1911
        day_obj = date(year, int(month), int(day))
        iso = day_obj.isoformat()
        js_weekday = (day_obj.weekday() + 1) % 7
        if WEEKDAY_CHARS[js_weekday] != wch:
            raise ValueError('weekday label mismatches Gregorian date: ' + iso)
        if (day_obj - base).days < 0 or (day_obj - base).days > 200:
            raise ValueError('announced added draw date outside safe future window: ' + iso)
        if int(period[:3]) != int(roc) or period in periods:
            raise ValueError('invalid or repeated draw term')
        for game in games:
            if js_weekday in BASE_WEEKDAYS[game]:
                raise ValueError('announced extra draw already a routine draw for ' + game + ': ' + iso)
        periods.add(period)
        dates.append(iso)
    if len(set(dates)) != expected or dates != sorted(dates):
        raise ValueError('extra dates must be unique and chronological')
    return dates


def strict_parse_spring_extra(text: str, title: str, url: str):
    if not source_is_official(url):
        raise ValueError('untrusted official URL')
    if not re.search(r'公告\s*\d{3}年春節加碼期間增加開獎日相關事宜', title):
        raise ValueError('notice not an exact supported spring calendar template')
    published = re.search(r'(\d{3})年(\d{1,2})月(\d{1,2})日\s*發布', text)
    if not published:
        raise ValueError('official publishing date missing')
    roc, m, d = map(int, published.groups())
    published_date = date(roc + 1911, m, d)
    if any(marker not in text for marker in ('壹、', '貳、', '參、')):
        raise ValueError('unexpected notice section layout')
    first = text.split('壹、', 1)[1].split('貳、', 1)[0]
    second = text.split('貳、', 1)[1].split('參、', 1)[0]
    if not ('大樂透' in first and '49樂合彩' in first and '春節' in first):
        raise ValueError('first section does not name the expected games')
    if not all(label in second for label in ('今彩539', '39樂合彩', '3星彩', '4星彩')):
        raise ValueError('second section does not name the expected games')
    first_games = ['lotto649', '49combo']
    second_games = ['539', '39combo', '3star', '4star']
    dates_lotto = row_list(first, published_date, first_games)
    dates_daily = row_list(second, published_date, second_games)
    result = {'lotto649': dates_lotto, '49combo': dates_lotto,
              '539': dates_daily, '39combo': dates_daily, '3star': dates_daily, '4star': dates_daily}
    return {'template': 'spring-extra-draw-days-v1', 'source': url, 'publishedDate': published_date.isoformat(), 'games': result}


def roc_news_indexes(today=None):
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    roc = today.year - 1911
    years = [roc]
    if today.month <= 3:
        years.append(roc - 1)
    if today.month >= 11:
        years.append(roc + 1)
    return [f'{OFFICIAL}news{year}.htm' for year in years]


def scan():
    settings = read_json(ROOT / 'config' / 'settings.json')
    seen_file = ROOT / 'state' / 'seen-notices.json'
    seen = read_json(seen_file)
    known = set(seen.get('urls', []))
    first_run = not known
    approved_file = ROOT / 'state' / 'auto-approved.json'
    approved = read_json(approved_file)
    pending_file = ROOT / 'state' / 'pending-notices.json'
    pending = read_json(pending_file)
    pending_by_url = {p['url']: p for p in pending['notices']}
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    relevant = {}
    succeeded = 0
    for url in roc_news_indexes():
        try:
            html = fetch_official(url)
            links = extract_relevant_links(html, url)
            if not links:
                # An unexpected empty official index is not evidence that notices were withdrawn.
                raise ValueError('no relevant announcement links in official news index')
            relevant.update(links)
            succeeded += 1
        except (OSError, HTTPError, URLError, ValueError, RuntimeError) as ex:
            print('Source unavailable (kept previous verified data):', url, str(ex), file=sys.stderr)
    if succeeded == 0:
        raise RuntimeError('No official source was readable; no changes to state or public data')
    added_auto = 0
    added_pending = 0
    for url, title in sorted(relevant.items()):
        if url in known:
            continue
        auto_record = None
        reason = '公告需人工確認：活動獎號、取消日期或未支援公告格式'
        if settings.get('autoApproveStrictSpringExtraDates', False) and '增加開獎日' in title and '春節' in title:
            try:
                detail = fetch_official(url)
                parser = OfficialHTML()
                parser.feed(detail)
                auto_record = strict_parse_spring_extra(parser.text(), title, url)
                if any(x.get('source') == url for x in approved['records']):
                    auto_record = None
                else:
                    approved['records'].append(auto_record)
                    added_auto += 1
            except (OSError, ValueError, RuntimeError) as ex:
                reason = '官方開獎日公告格式無法完整驗證：' + str(ex)[:180]
        if auto_record is None:
            pending_by_url[url] = {'url': url, 'title': title, 'detectedAt': stamp,
                                   'reason': reason, 'issueCreatedAt': None,
                                   'skipInitialIssue': first_run}
            added_pending += 1
        known.add(url)
    write_json(seen_file, {'schemaVersion': 1, 'urls': sorted(known)})
    write_json(pending_file, {'schemaVersion': 1, 'notices': list(pending_by_url.values())})
    if added_auto:
        write_json(approved_file, approved)
    print(f'Checked {succeeded} index pages; {len(relevant)} relevant notices; '
          f'{added_auto} strictly auto-approved; {added_pending} pending human review; '
          f'firstRun={first_run}')
    return added_auto, added_pending


if __name__ == '__main__':
    try:
        scan()
    except Exception as exc:
        print('MONITOR FAILED (no calendar overwrite):', exc, file=sys.stderr)
        sys.exit(1)
