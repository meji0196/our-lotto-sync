#!/usr/bin/env python3
"""Optionally open issues for new unreviewed official notices, never publish them."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from core import ROOT, read_json, write_json


def main():
    settings = read_json(ROOT / 'config' / 'settings.json')
    if not settings.get('createGitHubIssuesForPendingNotices'):
        print('Issue creation disabled by settings.')
        return
    token = os.environ.get('GH_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY')
    if not token or not repo or '/' not in repo:
        print('No GitHub Actions token/repository; pending notices remain visible in state/pending-notices.json')
        return
    path = ROOT / 'state' / 'pending-notices.json'
    info = read_json(path)
    changed = False
    for entry in info.get('notices', []):
        if entry.get('issueCreatedAt') or entry.get('skipInitialIssue'):
            continue
        body = (f'官方公告待核對（**尚未變更使用者開獎日曆**）\n\n'
                f'公告：{entry["title"][:200]}\n\n'
                f'來源：{entry["url"]}\n\n'
                f'原因：{entry["reason"][:250]}\n\n'
                '請檢查彩種、日期、期別、加碼開獎規則及活動提前結束條款；確認後才編輯 config/approved-calendar.json 或 approved-promotions.json。')
        data = json.dumps({'title': '【待核對】台彩公告：' + entry['title'][:75], 'body': body}, ensure_ascii=False).encode('utf-8')
        req = Request('https://api.github.com/repos/' + repo + '/issues', data=data,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(req, timeout=20) as res:
                issue = json.load(res)
            entry['issueCreatedAt'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            entry['issueUrl'] = issue.get('html_url', '')
            changed = True
            print('Created GitHub issue:', entry['issueUrl'])
        except (OSError, HTTPError) as exc:
            print('Could not create issue, will retry next day:', str(exc), file=sys.stderr)
    if changed:
        write_json(path, info)

if __name__ == '__main__':
    main()
