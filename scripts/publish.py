#!/usr/bin/env python3
"""Build a stable, versioned, read-only calendar API from confirmed sources."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys
from core import ROOT, BASE_WEEKDAYS, load_approved_config, load_auto_config, read_json, validate_promotions, write_json


def build():
    manual = load_approved_config(ROOT / 'config' / 'approved-calendar.json')
    auto = load_auto_config(ROOT / 'state' / 'auto-approved.json')
    promos = validate_promotions(ROOT / 'config' / 'approved-promotions.json')
    games = {}
    for game, weekdays in BASE_WEEKDAYS.items():
        games[game] = {
            'weekdays': weekdays,
            'addedDates': sorted(manual[game]['addedDates'] | auto[game]),
            'cancelledDates': sorted(manual[game]['cancelledDates']),
        }
        if set(games[game]['addedDates']) & set(games[game]['cancelledDates']):
            raise ValueError('Conflicting manual and automatic dates in ' + game)
    content = {'schemaVersion': 1, 'games': games, 'promotions': promos}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    path = ROOT / 'docs' / 'aoer-schedule.json'
    old = read_json(path) if path.exists() else None
    if old and {k: old.get(k) for k in ('schemaVersion', 'games', 'promotions')} == content:
        print('Unchanged: calendar remains at', old.get('issuedAt'))
        return False
    now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
    write_json(path, {'schemaVersion': 1, 'issuedAt': now, 'games': games, 'promotions': promos})
    write_json(ROOT / 'docs' / 'feed-status.json', {
        'schemaVersion': 1,
        'issuedAt': now,
        'revisionHash': digest[:16],
        'totalAddedDates': sum(len(g['addedDates']) for g in games.values()),
        'totalPromotions': len(promos),
        'service': 'our-lotto-calendar',
    })
    print('Published verified schedule:', now, 'hash:', digest[:16])
    return True


if __name__ == '__main__':
    try:
        build()
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print('BLOCKED publication:', str(exc), file=sys.stderr)
        sys.exit(1)
