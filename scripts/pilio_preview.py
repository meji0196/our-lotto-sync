#!/usr/bin/env python3
"""Publish clearly labelled *unverified* Pilio draw previews, never prize decisions.

Safety rule: Stars are paired on one page in this exact order: 3D (3 digits),
then 4D (4 digits). If the seven-digit draw block cannot be isolated exactly,
publish neither guessed star result nor a cached result from the faulty parser.
"""
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs' / 'early-draws.json'
TZ = timezone(timedelta(hours=8))
PAGES = {
    '539': ('main_lto539.asp', 5, 39, None),
    'lotto649': ('main_ltobig.asp', 6, 49, 49),
    'power': ('main_lto.asp', 6, 38, 8),
    '3star': ('main_lto34.asp', 3, 9, None),
    '4star': ('main_lto34.asp', 4, 9, None),
}


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.words = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored and data.strip():
            self.words.append(data.strip())


def parse_html(game, html, now=None):
    if game not in PAGES:
        raise ValueError('unknown game')
    parser = TextParser()
    parser.feed(html)
    lines = [v.strip() for word in parser.words for v in word.splitlines() if v.strip()]
    text = '\n'.join(lines)
    heading = re.search(r'(20\d{2})/(\d{1,2})/(\d{1,2})\s*[_（(]?[^\n]{0,30}?最新開獎號碼', text)
    if not heading:
        raise ValueError('latest draw date heading absent')
    draw_date = date(int(heading.group(1)), int(heading.group(2)), int(heading.group(3)))
    today = now or datetime.now(TZ).date()
    if draw_date > today or (today - draw_date).days > 2:
        raise ValueError(f'stale or future draw {draw_date}')
    # Only the block between the latest draw heading and the schedule caption
    # belongs to the visible latest draw balls, not tables or older drawings.
    after_heading = text[heading.end():]
    if '每週' not in after_heading:
        raise ValueError('draw block boundary absent')
    block = after_heading.split('每週', 1)[0]
    balls = [int(x) for x in re.findall(r'(?m)^\s*(\d{1,2})\s*$', block)]
    if game in ('3star', '4star'):
        # Pilio's main_lto34.asp displays: [3星彩 百 十 個] [4星彩 千 百 十 個].
        # DO NOT use first four / last three; that reverses/crosses both games.
        if len(balls) != 7 or any(not 0 <= n <= 9 for n in balls):
            raise ValueError(f'star draw block must contain exactly 7 digits, got {balls!r}')
        numbers = balls[:3] if game == '3star' else balls[3:]
        special = None
    else:
        _, count, max_ball, special_max = PAGES[game]
        required = count + (1 if special_max is not None else 0)
        if len(balls) != required:
            raise ValueError(f'ball count mismatch: expected {required}, got {len(balls)}')
        numbers = balls[:count]
        special = balls[count] if special_max is not None else None
        if len(set(numbers)) != count or any(not 1 <= n <= max_ball for n in numbers):
            raise ValueError('invalid or repeated draw numbers')
        if special_max is not None and not 1 <= special <= special_max:
            raise ValueError('invalid special ball')
    return {
        'date': draw_date.isoformat(), 'numbers': numbers,
        'special': special, 'source': 'pilio', 'verified': False,
    }


def fetch_html(page):
    url = 'https://www.pilio.idv.tw/' + page
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; OurLottoSync/1.1; website-monitor)'})
    with urllib.request.urlopen(req, timeout=13) as response:
        raw = response.read(700000)
        declared = response.headers.get_content_charset() or 'utf-8'
    for codec in dict.fromkeys((declared, 'big5', 'cp950', 'utf-8')):
        try:
            html = raw.decode(codec, errors='strict')
        except (UnicodeError, LookupError):
            continue
        if '最新開獎號碼' in html:
            return html
    raise ValueError(f'cannot decode draw heading from {page}')


def build_feed(now, existing, fetch=fetch_html):
    games = {}
    fetched = {}
    for game, (page, _, _, _) in PAGES.items():
        try:
            if page not in fetched:
                fetched[page] = fetch(page)
            games[game] = parse_html(game, fetched[page], now.date())
            print('OK', game, games[game]['date'])
        except Exception as error:
            print('SKIP', game, str(error), file=sys.stderr)
            # Existing 3D/4D entries could have been produced by a broken parser.
            # Never re-publish them; fail closed until a valid 7-digit block arrives.
            if game in ('3star', '4star'):
                continue
            previous = existing.get(game)
            if not isinstance(previous, dict):
                continue
            try:
                age = (now.date() - date.fromisoformat(previous['date'])).days
                if (0 <= age <= 2 and previous.get('source') == 'pilio'
                        and previous.get('verified') is False):
                    games[game] = previous
            except (ValueError, TypeError, KeyError):
                continue
    return games


def main():
    old = {}
    if DEST.exists():
        try:
            old = json.loads(DEST.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    now = datetime.now(TZ)
    games = build_feed(now, old.get('games', {}) if isinstance(old.get('games'), dict) else {})
    # Crucial: stale/incorrect old star results are removed even if today's
    # site format changes, instead of remaining indefinitely in public JSON.
    if games == old.get('games') and old.get('schemaVersion') == 1:
        print('No changed previews; retaining existing issue time')
        return 0
    payload = {
        'schemaVersion': 1,
        'issuedAt': now.isoformat(timespec='seconds'),
        'purpose': 'PRELIMINARY_DISPLAY_ONLY',
        'games': games,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Published changes:', ', '.join(sorted(games)) or '(no verified-layout previews)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
