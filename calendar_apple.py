"""Calendar bridge. Arguments are passed as data, never interpolated into script."""
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from runtime import DEMO

CALENDAR = os.getenv('AGENT_CALENDAR', 'AI助理')
SCRIPT = '''
use framework "Foundation"
use scripting additions
on run argv
 set action to item 1 of argv
 set cname to item 2 of argv
 tell application "/System/Applications/Calendar.app"
  set cs to every calendar whose name is cname
  if (count cs) > 1 then error "存在多个同名日历，请设置唯一的 AGENT_CALENDAR"
  if (count cs) = 0 then
   if action is "delete" then return "missing"
   error "请先在日历 App 的 iCloud 账户下创建名为 AI助理 的日历"
  else
   set c to item 1 of cs
  end if
  if not writable of c then error "日历不可写"
  set marker to item 3 of argv
  set foundEvents to every event of c whose description starts with (marker & linefeed)
  if action is "delete" then
   repeat with e in foundEvents
    delete e
   end repeat
   return "ok"
  end if
  set s to my epochDate(item 5 of argv)
  set finishDate to my epochDate(item 6 of argv)
  if (count foundEvents) > 1 then error "发现重复的同步标记，请先检查日历"
  if (count foundEvents) = 0 then
   set e to make new event at c with properties {summary:item 4 of argv, start date:s, end date:finishDate, description:(marker & linefeed & item 10 of argv), location:item 7 of argv, «class wrad»:(item 8 of argv is "true")}
   tell e to make new display alarm  with properties {trigger interval:(item 9 of argv as integer)}
  else
   set e to item 1 of foundEvents
   set properties of e to {summary:item 4 of argv, start date:s, end date:finishDate, description:(marker & linefeed & item 10 of argv), location:item 7 of argv, «class wrad»:(item 8 of argv is "true")}
  end if
  return uid of e
 end tell
end run
on epochDate(v)
 return (current application's NSDate's dateWithTimeIntervalSince1970:(v as real)) as date
end epochDate
'''

def offset(value):
    # Calendar AppleScript dates use the Mac's local timezone.
    tz = ZoneInfo(os.getenv('AGENT_TZ', 'Australia/Sydney'))
    dt = datetime.strptime(value, '%Y-%m-%d %H:%M').replace(tzinfo=tz)
    return str(int(dt.timestamp()))

def sync(kind, ident, title='', start='', end='', location='', delete=False, all_day=False, details='', alarm=-15):
    if DEMO:
        return 'demo-only-no-calendar-access'
    marker = f'AI助理管理 / {kind} / {ident}'
    args = ['delete' if delete else 'upsert', CALENDAR, marker]
    if not delete:
        args += [title, offset(start), offset(end), location, str(all_day).lower(), str(alarm), details]
    r = subprocess.run(['/usr/bin/osascript', '-e', SCRIPT, *args], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or '日历同步失败')
    return r.stdout.strip()
