#!/usr/bin/env python3
"""Publish unverified previews from the Our Lotto results API, with Pilio fallback.

The consuming app MUST verify official draws and prize money independently.
This feed intentionally never sets verified=True, even if the results website
reports that it retrieved a row from Taiwan Lottery's official API.

Run in GitHub Actions (server-to-server) rather than the browser, where the
Our Lotto site does not currently permit cross-origin API fetches.
"""

import json
import re
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pilio_preview

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs' / 'early-draws.json'
TZ = pilio_preview.TZ
OUR_RESULTS_BASE = 'https://lotto-glass-board.workspace-840742.chatgpt.site/api/results?game='

# Key names and the output schema remain compatible with V14-CA / V14-BW.
GAME_MAP = {
    '539': ('daily', 5, 39, None),
    'lotto649': ('lotto', 6, 49, 49),
    'power': ('power', 6, 38, 8),
    '3star': ('three', 3, 9, None),
    '4star': ('four', 4, 9, None),
}
MAX_AGE_DAYS = 2


class SourceConflict(ValueError):
    """Newer source explicitly flags a conflict: do not trust Pilio either."""


def strict_int(value):
    return type(value) is int


def validate_draw(game, draw, today):
    """Check a single provisional record, without asserting official validity."""
    if game not in GAME_MAP or not isinstance(draw, dict):
        raise ValueError('invalid game or draw')
    raw_date = draw.get('date')
    if not isinstance(raw_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date):
        raise ValueError('date must be YYYY-MM-DD')
    try:
        draw_date = date.fromisoformat(raw_date)
    except ValueError as error:
        raise ValueError('invalid draw date') from error
    age = (today - draw_date).days
    if age < 0 or age > MAX_AGE_DAYS:
        raise ValueError('future/stale draw: ' + raw_date)
    _, count, max_value, special_max = GAME_MAP[game]
    nums = draw.get('numbers')
    if not isinstance(nums, list) or len(nums) != count:
        raise ValueError(f'incorrect count for {game}')
    if any(not strict_int(x) or x < (0 if game in ('3star', '4star') else 1)
           or x > max_value for x in nums):
        raise ValueError('number outside legal range')
    if game not in ('3star', '4star') and len(set(nums)) != count:
        raise ValueError('repeated ball number')
    special = draw.get('special')
    if special_max is None:
        if special is not None:
            raise ValueError('unexpected special ball')
    elif not strict_int(special) or not 1 <= special <= special_max:
        raise ValueError('incorrect special ball')
    elif game == 'lotto649' and special in nums:
        raise ValueError('lotto special ball repeats main ball')
    return True


def parse_our_results(game, payload, today):
    """Use the latest API row; fail closed when the newest row has a conflict."""
    api_game = GAME_MAP[game][0]
    if not isinstance(payload, dict) or payload.get('game') != api_game:
        raise ValueError('API game mismatch')
    if payload.get('stale') is not False:
        raise ValueError('Our Lotto API marked stale or unknown')
    rows = payload.get('rows')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError('API rows missing or invalid')
    top = rows[0]
    if not isinstance(top, dict):
        raise ValueError('latest row not an object')
    if top.get('conflict') is not False:
        # A present, explicit False is required. Do not silently ignore missing
        # conflict metadata or defer to the same upstream third-party source.
        raise SourceConflict('latest row conflicting or missing conflict status')
    src = top.get('source')
    if src not in ('official', 'third'):
        raise ValueError('unexpected upstream source')
    # A blank draw period is legitimate before official publication. An
    # official-source row, however, should have a confirmed 9-digit period.
    period = top.get('period', '')
    if not isinstance(period, str) or (period and not re.fullmatch(r'\d{9}', period)):
        raise ValueError('invalid draw period')
    if src == 'official' and not period:
        raise ValueError('official-source row missing period')
    original = top.get('sourceUrl')
    if original is not None:
        if not isinstance(original, str) or len(original) > 600:
            raise ValueError('invalid source URL')
        u = urlsplit(original)
        if u.scheme != 'https' or not u.hostname:
            raise ValueError('non-HTTPS source URL')
        if src == 'official' and u.hostname != 'api.taiwanlottery.com':
            raise ValueError('official-source row must point to Taiwan Lottery API')
    draw = {
        'date': top.get('date'),
        'numbers': top.get('numbers'),
        'special': top.get('special'),
    }
    validate_draw(game, draw, today)
    # Prevent a malformed feed whose first row is not actually the newest.
    for other in rows[1:4]:
        if isinstance(other, dict) and isinstance(other.get('date'), str):
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', other['date']) and other['date'] > draw['date']:
                raise ValueError('API rows not sorted newest first')
    return {
        **draw,
        'source': 'our-lotto',       # Aggregator/proxy name, NOT independent verification.
        'upstreamSource': src,       # "third" may itself be pilio.idv.tw.
        'verified': False,
        'period': period,
        'sourceUrl': original or OUR_RESULTS_BASE + api_game,
    }


def fetch_our_results(api_game):
    if api_game not in {x[0] for x in GAME_MAP.values()}:
        raise ValueError('unknown API game')
    url = OUR_RESULTS_BASE + api_game
    request = urllib.request.Request(url, headers={
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (compatible; OurLottoSync/1.3; lottery-data-mirror)',
        'Cache-Control': 'no-cache',
    })
    with urllib.request.urlopen(request, timeout=18) as response:
        content_type = response.headers.get('Content-Type', '')
        if 'json' not in content_type.lower():
            raise ValueError('non-JSON response')
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('API response too large')
    return json.loads(raw.decode('utf-8'))


def safe_previous(game, previous, now):
    """Keep only a recent, structurally valid preview if both sources fail.

    Do not carry forward 3/4-star rows on failure: the old parser once
    produced realistic-looking but incorrect digits.
    """
    if game in ('3star', '4star') or not isinstance(previous, dict):
        return None
    if previous.get('source') not in ('pilio', 'our-lotto') or previous.get('verified') is not False:
        return None
    try:
        validate_draw(game, previous, now.date())
        return previous
    except (ValueError, KeyError, TypeError):
        return None


def build_feed(now, existing, fetch_our=fetch_our_results,
               fetch_pilio=pilio_preview.fetch_html, quarantined=None):
    """Primary Our Lotto JSON; Pilio as backup; recent cache last.

    Injected fetchers allow fully offline unit tests. Each is called only for
    its supported fixed page/identifier, never for arbitrary source URLs.
    """
    games = {}
    cached_pilio = {}
    for game, (api_game, _, _, _) in GAME_MAP.items():
        conflict = False
        try:
            response = fetch_our(api_game)
            games[game] = parse_our_results(game, response, now.date())
            print('OUR-LOTTO', game, games[game]['date'], games[game]['upstreamSource'])
            continue
        except SourceConflict as error:
            print('QUARANTINE', game, error, file=sys.stderr)
            conflict = True
        except Exception as error:
            print('OUR-LOTTO SKIP', game, error, file=sys.stderr)
        if conflict:
            if quarantined is not None:
                quarantined.add(game)
            # Do not reuse Pilio when the aggregator has explicitly identified a
            # conflict, since the two may refer to the SAME original Pilio row.
            continue
        page = pilio_preview.PAGES[game][0]
        try:
            if page not in cached_pilio:
                cached_pilio[page] = fetch_pilio(page)
            games[game] = pilio_preview.parse_html(game, cached_pilio[page], now.date())
            validate_draw(game, games[game], now.date())
            print('PILIO FALLBACK', game, games[game]['date'])
            continue
        except Exception as error:
            print('PILIO SKIP', game, error, file=sys.stderr)
        previous = safe_previous(game, existing.get(game), now)
        if previous is not None:
            games[game] = previous
            print('UNCHANGED CACHE', game, previous['date'])
    return games


def main():
    old = {}
    if DEST.exists():
        try:
            old = json.loads(DEST.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            pass
    now = datetime.now(TZ)
    quarantined = set()
    games = build_feed(now, old.get('games', {}) if isinstance(old.get('games'), dict) else {},
                       quarantined=quarantined)
    if not games and not quarantined:
        # Never publish an empty feed due to a temporary network outage.
        # There may still be cached previews in the previous file; the app
        # independently rejects these when they become too old.
        print('No publishable previews; leaving existing file unchanged')
        return 0
    if games == old.get('games') and old.get('schemaVersion') == 1:
        print('Unchanged; retaining original issuedAt')
        return 0
    output = {
        'schemaVersion': 1,
        'issuedAt': now.isoformat(timespec='seconds'),
        'purpose': 'PRELIMINARY_DISPLAY_ONLY',
        'games': games,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Published', ', '.join(sorted(games)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
