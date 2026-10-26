"""Durable task storage and a retryable Calendar outbox."""
from datetime import timedelta
import uuid
import calendar_apple


def install(a):
    original_db = a.db
    def db():
        c = original_db()
        c.executescript('''
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL,
          due TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS calendar_outbox(kind TEXT, ident INTEGER,
          action TEXT NOT NULL, PRIMARY KEY(kind,ident));
        CREATE TABLE IF NOT EXISTS digest_cache(day TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE IF NOT EXISTS organizer_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        c.execute('INSERT OR IGNORE INTO organizer_meta VALUES(?,?)', ('store_id', str(uuid.uuid4())))
        if not c.execute("SELECT value FROM organizer_meta WHERE key='migrated'").fetchone():
            c.execute("INSERT OR IGNORE INTO calendar_outbox SELECT 'event', id, 'upsert' FROM events")
            c.execute("INSERT INTO organizer_meta VALUES('migrated','1')")
        c.commit()
        return c
    a.db = db

    def queue(c, kind, ident, action='upsert'):
        c.execute('INSERT OR REPLACE INTO calendar_outbox VALUES(?,?,?)', (kind, ident, action))

    def sync_calendar():
        errors, synced = [], 0
        with db() as c:
            pending = c.execute('SELECT * FROM calendar_outbox').fetchall()
            store = c.execute('SELECT value FROM organizer_meta WHERE key=?', ('store_id',)).fetchone()[0]
        for p in pending:
            kind, ident, action = p['kind'], p['ident'], p['action']
            with db() as c:
                r = c.execute(f'SELECT * FROM {"events" if kind == "event" else "tasks"} WHERE id=?', (ident,)).fetchone()
            try:
                if action == 'delete' or r is None or (kind == 'task' and r['completed']):
                    calendar_apple.sync(kind, f'{store}/{ident}', delete=True)
                elif kind == 'event':
                    calendar_apple.sync(kind, f'{store}/{ident}', r['title'], r['start'], r['end'], r['location'])
                else:
                    s = a.parse_dt(r['due']).replace(hour=0, minute=0)
                    calendar_apple.sync(kind, f'{store}/{ident}', '待办：' + r['title'], s.strftime(a.FMT),
                                        (s + timedelta(days=1)).strftime(a.FMT), all_day=True)
                with db() as c:
                    c.execute('DELETE FROM calendar_outbox WHERE kind=? AND ident=? AND action=?', (kind, ident, action))
                synced += 1
            except Exception as ex:
                errors.append({'kind': kind, 'id': ident, 'error': str(ex)})
        if not errors:
            try:
                refresh_digests()
            except Exception as ex:
                errors.append({'kind':'digest', 'error':str(ex)})
        return {'ok': not errors, 'synced': synced, 'errors': errors}

    def refresh_digests():
        import json
        with db() as c:
            tasks = [dict(r) for r in c.execute('SELECT * FROM tasks WHERE completed=0 ORDER BY due')]
            events = [dict(r) for r in c.execute('SELECT * FROM events ORDER BY start')]
            store = c.execute("SELECT value FROM organizer_meta WHERE key='store_id'").fetchone()[0]
        n = a.now()
        for offset in range(35):
            day = (n + timedelta(days=offset)).replace(hour=9, minute=0, second=0, microsecond=0)
            if day <= n:
                continue
            key = day.strftime('%Y-%m-%d')
            end = day.replace(hour=0) + timedelta(days=1)
            today_tasks = [r for r in tasks if day.replace(hour=0) <= a.parse_dt(r['due']) < end]
            today_events = [r for r in events if a.parse_dt(r['start']) < end and a.parse_dt(r['end']) > day.replace(hour=0)]
            week_end = day.replace(hour=0) + timedelta(days=7)
            week_tasks = [r for r in tasks if day.replace(hour=0) <= a.parse_dt(r['due']) < week_end] if day.weekday() == 0 else []
            week_events = [r for r in events if a.parse_dt(r['start']) < week_end and a.parse_dt(r['end']) > day.replace(hour=0)] if day.weekday() == 0 else []
            if not (today_tasks or today_events or week_tasks or week_events):
                with db() as c:
                    cached = c.execute('SELECT day FROM digest_cache WHERE day=?', (key,)).fetchone()
                if cached:
                    calendar_apple.sync('digest', f'{store}/{key}', delete=True)
                    with db() as c:
                        c.execute('DELETE FROM digest_cache WHERE day=?', (key,))
                continue
            lines = ['今日待办'] + [r['due'] + ' ' + r['title'] for r in today_tasks]
            if not today_tasks: lines.append('无')
            lines += ['今日日程'] + [r['start'][11:] + ' ' + r['title'] for r in today_events]
            if not today_events: lines.append('无')
            if day.weekday() == 0:
                lines += ['本周待办'] + [r['due'] + ' ' + r['title'] for r in week_tasks]
                lines += ['本周日程'] + [r['start'] + ' ' + r['title'] for r in week_events]
            titles = [r['title'] for r in today_tasks] + [r['title'] for r in today_events]
            title = ('本周＋今日' if day.weekday() == 0 else '今日') + '：' + ('；'.join(titles) or '本周安排')
            if day.weekday() == 0: title += '（点开查看本周）'
            details = '\n'.join(lines)
            content = json.dumps([title, details], ensure_ascii=False)
            with db() as c:
                cached = c.execute('SELECT content FROM digest_cache WHERE day=?', (key,)).fetchone()
            if cached and cached[0] == content: continue
            calendar_apple.sync('digest', f'{store}/{key}', title, day.strftime(a.FMT),
                (day+timedelta(minutes=5)).strftime(a.FMT), details=details, alarm=0)
            with db() as c:
                c.execute('INSERT OR REPLACE INTO digest_cache VALUES(?,?)', (key, content))

    def result(out):
        if out.get('ok'):
            status = sync_calendar()
            out['calendar_synced'] = status['ok']
            if not status['ok']:
                out['warning'] = '本地已保存，日历同步失败；不要重复新增，使用 sync_calendar 重试。'
                out['sync_errors'] = status['errors']
        return out

    for name in ('add_event', 'update_event', 'delete_event'):
        old = getattr(a, name)
        def wrapped(*args, _name=name, _old=old, **kwargs):
            if _name == 'update_event':
                ident = kwargs.get('id', args[0] if args else None)
                with db() as c:
                    r = c.execute('SELECT * FROM events WHERE id=?', (ident,)).fetchone()
                if r:
                    s = a.parse_dt(kwargs.get('start') or r['start'])
                    e = a.parse_dt(kwargs['end']) if kwargs.get('end') else s + (a.parse_dt(r['end'])-a.parse_dt(r['start']))
                    if e <= s:
                        return {'ok':False, 'error':'结束时间必须晚于开始时间'}
            out = _old(*args, **kwargs)
            if out.get('ok'):
                ident = out.get('id', kwargs.get('id', args[0] if args else None))
                with db() as c:
                    queue(c, 'event', ident, 'delete' if _name == 'delete_event' else 'upsert')
                return result(out)
            return out
        setattr(a, name, wrapped)
        a.DISPATCH[name] = wrapped

    def add_task(title, due):
        d = a.parse_dt(due)
        with db() as c:
            cur = c.execute('INSERT INTO tasks(title,due) VALUES(?,?)', (title, d.strftime(a.FMT)))
            ident = cur.lastrowid
            queue(c, 'task', ident)
        return result({'ok':True, 'id':ident, 'title':title, 'due':d.strftime(a.FMT)})

    def list_tasks(include_completed=False):
        with db() as c:
            rows = c.execute('SELECT * FROM tasks WHERE completed=0 OR ? ORDER BY due', (include_completed,)).fetchall()
        return {'tasks':[dict(r) for r in rows]}

    def complete_task(id):
        with db() as c:
            if not c.execute('SELECT id FROM tasks WHERE id=?', (id,)).fetchone():
                return {'ok':False, 'error':'待办不存在'}
            c.execute('UPDATE tasks SET completed=1 WHERE id=?', (id,))
            queue(c, 'task', id, 'delete')
        return result({'ok':True})

    def update_task(id, title=None, due=None):
        with db() as c:
            r = c.execute('SELECT * FROM tasks WHERE id=?', (id,)).fetchone()
            if not r:
                return {'ok':False, 'error':'待办不存在'}
            value = a.parse_dt(due).strftime(a.FMT) if due else r['due']
            c.execute('UPDATE tasks SET title=?,due=? WHERE id=?', (title if title is not None else r['title'], value, id))
            queue(c, 'task', id, 'delete' if r['completed'] else 'upsert')
        return result({'ok':True})

    defs = [
      ('add_task', '记录有截止日期的待办，并作为全天事项同步日历。', {'title':a.S, 'due':a.DT('截止日期；只有日期可用 YYYY-MM-DD')}, ['title','due'], add_task),
      ('list_tasks', '查询待办和完成状态。', {'include_completed':a.B}, [], list_tasks),
      ('complete_task', '用户明确说完成后标记完成，并移除对应日历待办。', {'id':a.I}, ['id'], complete_task),
      ('update_task', '修改指定待办标题或截止日期。', {'id':a.I,'title':a.S,'due':a.S}, ['id'], update_task),
      ('sync_calendar', '重试之前失败的日历同步，不要重复新增事项。', {}, [], sync_calendar)]
    a.TOOLS[-1].pop('cache_control', None)
    for name, desc, props, required, fn in defs:
        a.TOOLS.append(a._t(name, desc, props, required))
        a.DISPATCH[name] = fn
    a.TOOLS[-1]['cache_control'] = {'type':'ephemeral'}
    return sync_calendar
