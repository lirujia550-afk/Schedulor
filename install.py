from pathlib import Path
import datetime,plistlib,shutil,sqlite3
src=Path(__file__).resolve().parent
old=Path.home()/'Desktop/note'
app=Path.home()/'Desktop/Schedulor.app'
if app.exists():raise SystemExit('Schedulor.app 已存在，未覆盖。')
contents=app/'Contents';data=contents/'Resources/note';binary=contents/'MacOS'
data.mkdir(parents=True);binary.mkdir()
for name in ['agent.py','notes_apple.py','organizer.py','calendar_apple.py','refresh.py','system_prompt.md']:
 shutil.copy2(old/name,data/name)
shutil.copytree(old/'.venv',data/'.venv',symlinks=True)
with sqlite3.connect(old/'assistant.db') as source, sqlite3.connect(data/'assistant.db') as target:source.backup(target)
if (old/'.window-settings.json').exists():
 shutil.copy2(old/'.window-settings.json',data/'.window-settings.json');(data/'.window-settings.json').chmod(0o600)
shutil.copy2(src/'assistant_window.py',data/'assistant_window.py')
(contents/'Info.plist').write_bytes(plistlib.dumps({
 'CFBundleName':'Schedulor','CFBundleDisplayName':'Schedulor','CFBundleIdentifier':'local.schedulor.desktop',
 'CFBundleExecutable':'launcher','CFBundlePackageType':'APPL','CFBundleVersion':'2','CFBundleShortVersionString':'2.0',
 'NSHighResolutionCapable':True,'LSArchitecturePriority':['arm64'],
 'NSAppleEventsUsageDescription':'管理你的 AI助理 专用笔记和日历。'}))
launcher=binary/'launcher'
launcher.write_text('''#!/bin/zsh
APP_DIR="${0:A:h:h:h}"
NOTE_DIR="$APP_DIR/Contents/Resources/note"
cd "$NOTE_DIR" || exit 1
exec /usr/bin/arch -arm64 "$NOTE_DIR/.venv/bin/python" "$NOTE_DIR/assistant_window.py" >> "$NOTE_DIR/window.log" 2>&1
''');launcher.chmod(0o755)
plist=Path.home()/'Library/LaunchAgents/local.personal-assistant.calendar-refresh.plist'
if plist.exists():
 shutil.copy2(plist,old/('calendar-refresh.plist.backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')))
 cfg=plistlib.loads(plist.read_bytes())
 cfg['ProgramArguments']=['/usr/bin/arch','-arm64',str(data/'.venv/bin/python'),str(data/'refresh.py')]
 cfg['WorkingDirectory']=str(data)
 cfg['StandardOutPath']=str(data/'calendar-refresh.log');cfg['StandardErrorPath']=str(data/'calendar-refresh.log')
 plist.write_bytes(plistlib.dumps(cfg))
print('已打包 Schedulor，数据库已一致性复制，原 note 保留为备份。')
