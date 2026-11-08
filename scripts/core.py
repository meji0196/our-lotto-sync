"""Shared safe publishing rules for the Our Lotto public calendar feed.

No third-party packages. Publishing data is not an API for placing wagers.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import json
import re

ROOT = Path(__file__).resolve().parents[1]
BASE_WEEKDAYS = {
    'lotto649': [2, 5],
    '49combo': [2, 5],
    'power': [1, 4],
    '539': [1, 2, 3, 4, 5, 6],
    '39combo': [1, 2, 3, 4, 5, 6],
    '3star': [1, 2, 3, 4, 5, 6],
    '4star': [1, 2, 3, 4, 5, 6],
    'bingo': [0, 1, 2, 3, 4, 5, 6],
}
URL_PATTERN = re.compile(r'^/news\d{7,8}\.htm$', re.I)


def read_json(path: Path):
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + '\n', encoding='utf-8')


def valid_iso(value: str) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def source_is_official(url: str) -> bool:
    if not isinstance(url, str):
        return False
    p = urlparse(url)
    return p.scheme == 'https' and p.netloc == 'lotto.ctbcbank.com' and bool(URL_PATTERN.fullmatch(p.path)) and not p.query and not p.fragment


def valid_records(records, label):
    if not isinstance(records, list) or len(records) > 500:
        raise ValueError(f'{label} must be an array of <=500 records')
    out = set()
    for item in records:
        if not isinstance(item, dict) or not valid_iso(item.get('date')):
            raise ValueError(f'{label}: invalid Gregorian ISO date')
        if not source_is_official(item.get('source')):
            raise ValueError(f'{label}: source must be an approved official HTTPS news URL')
        if item.get('confirmed') is not True:
            raise ValueError(f'{label}: only confirmed records may publish')
        if 'period' in item and not re.fullmatch(r'\d{9}', str(item['period'])):
            raise ValueError(f'{label}: invalid period')
        if item['date'] in out:
            raise ValueError(f'{label}: duplicate date')
        out.add(item['date'])
    return out


def load_approved_config(path: Path):
    cfg = read_json(path)
    games = cfg.get('games')
    if cfg.get('schemaVersion') != 1 or not isinstance(games, dict) or set(games) != set(BASE_WEEKDAYS):
        raise ValueError('approved-calendar must define all eight game keys and schemaVersion 1')
    clean = {}
    for game, rules in games.items():
        if not isinstance(rules, dict):
            raise ValueError(game + ': not an object')
        adds = valid_records(rules.get('addedDates', []), game + '.addedDates')
        cancels = valid_records(rules.get('cancelledDates', []), game + '.cancelledDates')
        if adds & cancels:
            raise ValueError(game + ': cannot add and cancel the same draw date')
        for item in rules.get('addedDates', []):
            day = date.fromisoformat(item['date'])
            weekday_js = (day.weekday() + 1) % 7
            if weekday_js in BASE_WEEKDAYS[game]:
                # A regular draw is redundant but not dangerous; reject to flag mistakes.
                raise ValueError(f'{game}: added date is already a normal draw: {item["date"]}')
        clean[game] = {'addedDates': adds, 'cancelledDates': cancels}
    return clean


def load_auto_config(path: Path):
    content = read_json(path)
    if content.get('schemaVersion') != 1 or not isinstance(content.get('records'), list):
        raise ValueError('auto-approved records schema invalid')
    out = {game: set() for game in BASE_WEEKDAYS}
    for rec in content['records']:
        if rec.get('template') != 'spring-extra-draw-days-v1' or not source_is_official(rec.get('source')):
            raise ValueError('unexpected automatically approved notice or source')
        for game, dates in rec.get('games', {}).items():
            if game not in out or not isinstance(dates, list):
                raise ValueError('auto-approved games invalid')
            for iso in dates:
                if not valid_iso(iso):
                    raise ValueError('auto-approved date invalid')
                out[game].add(iso)
    return out


def validate_promotions(path: Path):
    cfg = read_json(path)
    if cfg.get('schemaVersion') != 1 or not isinstance(cfg.get('promotions'), list) or len(cfg['promotions']) > 30:
        raise ValueError('promotions config schema invalid')
    validated = []
    for p in cfg['promotions']:
        mandatory = ('id', 'title', 'start', 'end', 'lastDrawDate', 'hideAfter', 'officialRules', 'numbersSource', 'verification', 'draws')
        if not isinstance(p, dict) or any(k not in p for k in mandatory):
            raise ValueError('promotion missing required fields')
        if not re.fullmatch('[A-Za-z0-9_-]{1,90}', p['id']) or not (0 < len(p['title']) <= 80):
            raise ValueError('promotion id/title invalid')
        if not all(valid_iso(p[k]) for k in ('start', 'end', 'lastDrawDate', 'hideAfter')):
            raise ValueError('promotion dates invalid')
        if not (p['start'] <= p['lastDrawDate'] <= p['end'] <= p['hideAfter']):
            raise ValueError('promotion date order invalid')
        if not source_is_official(p['officialRules']):
            raise ValueError('promotion requires official source')
        if p['verification'] not in ('official-verified', 'media-reported'):
            raise ValueError('promotion verification label invalid')
        if not isinstance(p['draws'], list) or len(p['draws']) > 100:
            raise ValueError('promotion draws invalid')
        periods = set()
        for draw in p['draws']:
            if not re.fullmatch(r'\d{9}', str(draw.get('period', ''))) or not valid_iso(draw.get('date')):
                raise ValueError('promotion period/date invalid')
            nums = draw.get('numbers')
            if not isinstance(nums, list) or len(nums) != 8 or any(type(n) is not int or not 1 <= n <= 49 for n in nums) or len(set(nums)) != 8:
                raise ValueError('promotion needs eight unique 1-49 numbers')
            if draw['period'] in periods:
                raise ValueError('duplicate promotion period')
            if not p['start'] <= draw['date'] <= p['end']:
                raise ValueError('promotion draw date outside campaign')
            periods.add(draw['period'])
        validated.append(p)
    return validated
