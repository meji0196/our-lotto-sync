#!/usr/bin/env python3
"""Fetch latest public draw numbers; preliminary ONLY, never publish prize decisions.
Run in GitHub Actions, not inside mobile clients.
"""
import json, re, sys, urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'docs'/'early-draws.json'
TZ=timezone(timedelta(hours=8))
PAGES={
 '539':('main_lto539.asp',5,39,None),
 'lotto649':('main_ltobig.asp',6,49,49),
 'power':('main_lto.asp',6,38,8),
 '3star':('main_lto34.asp',7,9,None),
 '4star':('main_lto34.asp',7,9,None)
}
class TextParser(HTMLParser):
 def __init__(self):super().__init__();self.words=[];self.ignored=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style'):self.ignored+=1
 def handle_endtag(self,tag):
  if tag in ('script','style') and self.ignored:self.ignored-=1
 def handle_data(self,data):
  if not self.ignored and data.strip():self.words.append(data.strip())

def parse_html(game,html,now=None):
 p=TextParser();p.feed(html);lines=[v for word in p.words for v in word.splitlines() if v.strip()]
 text='\n'.join(lines)
 m=re.search(r'(20\d{2})/(\d{1,2})/(\d{1,2})\s*[_（(]?[^\n]{0,30}?最新開獎號碼',text)
 if not m:raise ValueError('latest draw date heading absent')
 date=f'{m.group(1)}-{int(m.group(2)):02}-{int(m.group(3)):02}'
 check=datetime.fromisoformat(date).date()
 now=now or datetime.now(TZ).date()
 if check>now or (now-check).days>2:raise ValueError('stale or future draw '+date)
 segment=text[m.end():].split('每週',1)[0]
 # Page numbers are separate text nodes. Stop immediately after expected balls and second-zone ball.
 balls=[int(v) for v in re.findall(r'(?m)^\s*(\d{1,2})\s*$',segment)]
 _,count,maxball,specialmax=PAGES[game]
 if game in ('3star','4star'):
  if len(balls)<7:raise ValueError('star ball count wrong')
  numbers=balls[-3:] if game=='3star' else balls[:4]
  if len(numbers)!=(3 if game=='3star' else 4) or any(v<0 or v>9 for v in numbers):raise ValueError('star digit invalid')
  sp=None
 else:
  if len(balls)<count+(1 if specialmax else 0):raise ValueError('ball count wrong')
  numbers=balls[:count];sp=balls[count] if specialmax else None
  if len(set(numbers))!=count or any(v<1 or v>maxball for v in numbers):raise ValueError('invalid ball numbers')
  if specialmax and not(1<=sp<=specialmax):raise ValueError('invalid special ball')
 return {'date':date,'numbers':numbers,'special':sp,'source':'pilio','verified':False}

def main():
 existing={}
 if DEST.exists():
  try:existing=json.loads(DEST.read_text(encoding='utf-8')).get('games',{})
  except (ValueError,OSError):pass
 now=datetime.now(TZ)
 results={}
 for game,(page,*_) in PAGES.items():
  try:
   req=urllib.request.Request('https://www.pilio.idv.tw/'+page,headers={'User-Agent':'Mozilla/5.0 (compatible; OurLottoSync/1.0; website-monitor)'})
   with urllib.request.urlopen(req,timeout=13) as res:
    charset=res.headers.get_content_charset() or 'utf-8';raw=res.read(700000);html=raw.decode(charset,errors='replace');
    if '最新開獎號碼' not in html:
     for candidate in ('big5','cp950','utf-8'):
      alternate=raw.decode(candidate,errors='replace')
      if '最新開獎號碼' in alternate:html=alternate;break
   results[game]=parse_html(game,html,now.date());print('OK',game,results[game]['date'])
  except Exception as e:
   print('SKIP',game,str(e),file=sys.stderr)
   if game in existing:
    try:
     age=(now.date()-datetime.fromisoformat(existing[game]['date']).date()).days
     if 0<=age<=2 and existing[game].get('source')=='pilio' and existing[game].get('verified') is False:results[game]=existing[game]
    except Exception:pass
 if not results:
  print('No valid results; retaining last feed without touching timestamp')
  return 0
 obj={'schemaVersion':1,'issuedAt':now.isoformat(timespec='seconds'),'purpose':'PRELIMINARY_DISPLAY_ONLY','games':results}
 rendered=json.dumps(obj,ensure_ascii=False,indent=2)+'\n'
 if not DEST.exists() or DEST.read_text(encoding='utf-8')!=rendered:DEST.write_text(rendered,encoding='utf-8')
 return 0
if __name__=='__main__':raise SystemExit(main())
