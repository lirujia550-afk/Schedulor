"""
个人助理 Agent：聊天记笔记 / 整理笔记 / 安排日程
运行：
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-...
    python agent.py
可选环境变量：AGENT_TZ（默认 Australia/Sydney）、AGENT_MODEL、AGENT_DB
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from runtime import DATA_DIR, DEMO

TZ = ZoneInfo(os.getenv("AGENT_TZ", "Australia/Sydney"))
MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-5-5")
DB_PATH = os.getenv("AGENT_DB", str(DATA_DIR / "assistant.db"))
FMT = "%Y-%m-%d %H:%M"


# ───────────────────────── 存储层 ─────────────────────────
class ManagedConnection(sqlite3.Connection):
    """Commit/rollback and release file handles when leaving a with block."""
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def db():
    conn = sqlite3.connect(DB_PATH, factory=ManagedConnection)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, content TEXT NOT NULL, tags TEXT DEFAULT '',
            created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
            location TEXT DEFAULT '', notes TEXT DEFAULT '');
        """
    )
    return conn


def now():
    return datetime.now(TZ).replace(tzinfo=None)


def parse_dt(s: str) -> datetime:
    s = s.strip().replace("T", " ")
    for f in (FMT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, f)
        except ValueError:
            pass
    raise ValueError(f"时间格式不对：{s}，请使用 YYYY-MM-DD HH:MM")


def norm_tags(tags):
    return ",".join(sorted({t.strip().lstrip("#") for t in (tags or []) if t.strip()}))


def row(r):
    return dict(r) if r else None


# ───────────────────────── 笔记工具 ─────────────────────────
def save_note(content, title="", tags=None):
    ts = now().strftime(FMT)
    with db() as c:
        cur = c.execute(
            "INSERT INTO notes(title,content,tags,created_at,updated_at) VALUES(?,?,?,?,?)",
            (title, content, norm_tags(tags), ts, ts),
        )
    return {"ok": True, "id": cur.lastrowid}


def search_notes(query="", tag="", limit=10):
    kws = [k for k in query.split() if k]
    with db() as c:
        rows = c.execute("SELECT * FROM notes ORDER BY updated_at DESC").fetchall()
    scored = []
    for r in rows:
        if tag and tag.lstrip("#") not in r["tags"].split(","):
            continue
        text = f'{r["title"]} {r["content"]} {r["tags"]}'.lower()
        score = sum(k.lower() in text for k in kws) if kws else 1
        if score:
            scored.append((score, row(r)))
    scored.sort(key=lambda x: -x[0])
    return {"count": len(scored), "notes": [n for _, n in scored[:limit]]}


def list_notes(tag="", limit=20):
    return search_notes("", tag, limit)


def update_note(id, content=None, title=None, tags=None):
    with db() as c:
        r = c.execute("SELECT * FROM notes WHERE id=?", (id,)).fetchone()
        if not r:
            return {"ok": False, "error": f"笔记 {id} 不存在"}
        c.execute(
            "UPDATE notes SET title=?,content=?,tags=?,updated_at=? WHERE id=?",
            (
                title if title is not None else r["title"],
                content if content is not None else r["content"],
                norm_tags(tags) if tags is not None else r["tags"],
                now().strftime(FMT),
                id,
            ),
        )
    return {"ok": True}


def delete_note(id, confirmed=False):
    if not confirmed:
        return {"ok": False, "need_confirm": True, "hint": "请先向用户确认后再以 confirmed=true 调用"}
    with db() as c:
        c.execute("DELETE FROM notes WHERE id=?", (id,))
    return {"ok": True}


# ───────────────────────── 日程工具 ─────────────────────────
def _conflicts(c, start, end, exclude_id=None):
    rows = c.execute(
        "SELECT * FROM events WHERE start < ? AND end > ? AND id != ?",
        (end.strftime(FMT), start.strftime(FMT), exclude_id or -1),
    ).fetchall()
    return [row(r) for r in rows]


def add_event(title, start, end="", duration_minutes=60, location="", notes="", force=False):
    s = parse_dt(start)
    e = parse_dt(end) if end else s + timedelta(minutes=duration_minutes)
    if e <= s:
        return {"ok": False, "error": "结束时间必须晚于开始时间"}
    with db() as c:
        clash = _conflicts(c, s, e)
        if clash and not force:
            return {"ok": False, "conflict": True, "conflicts_with": clash,
                    "hint": "存在冲突，请询问用户是改期还是仍要添加（force=true）"}
        cur = c.execute(
            "INSERT INTO events(title,start,end,location,notes) VALUES(?,?,?,?,?)",
            (title, s.strftime(FMT), e.strftime(FMT), location, notes),
        )
    return {"ok": True, "id": cur.lastrowid, "start": s.strftime(FMT), "end": e.strftime(FMT)}


def list_events(start_date="", end_date=""):
    s = parse_dt(start_date) if start_date else now().replace(hour=0, minute=0)
    e = parse_dt(end_date) + timedelta(days=1) if end_date else s + timedelta(days=7)
    with db() as c:
        rows = c.execute(
            "SELECT * FROM events WHERE start >= ? AND start < ? ORDER BY start",
            (s.strftime(FMT), e.strftime(FMT)),
        ).fetchall()
    return {"count": len(rows), "events": [row(r) for r in rows]}


def update_event(id, title=None, start=None, end=None, location=None, notes=None, force=False):
    with db() as c:
        r = c.execute("SELECT * FROM events WHERE id=?", (id,)).fetchone()
        if not r:
            return {"ok": False, "error": f"日程 {id} 不存在"}
        s = parse_dt(start) if start else parse_dt(r["start"])
        if end:
            e = parse_dt(end)
        elif start:  # 只改开始时间 → 保持原时长
            e = s + (parse_dt(r["end"]) - parse_dt(r["start"]))
        else:
            e = parse_dt(r["end"])
        clash = _conflicts(c, s, e, exclude_id=id)
        if clash and not force:
            return {"ok": False, "conflict": True, "conflicts_with": clash}
        c.execute(
            "UPDATE events SET title=?,start=?,end=?,location=?,notes=? WHERE id=?",
            (title or r["title"], s.strftime(FMT), e.strftime(FMT),
             location if location is not None else r["location"],
             notes if notes is not None else r["notes"], id),
        )
    return {"ok": True}


def delete_event(id, confirmed=False):
    if not confirmed:
        return {"ok": False, "need_confirm": True, "hint": "请先向用户确认后再以 confirmed=true 调用"}
    with db() as c:
        c.execute("DELETE FROM events WHERE id=?", (id,))
    return {"ok": True}


def find_free_slots(date, duration_minutes=60, day_start="09:00", day_end="18:00"):
    d = parse_dt(date).date()
    ws = datetime.combine(d, datetime.strptime(day_start, "%H:%M").time())
    we = datetime.combine(d, datetime.strptime(day_end, "%H:%M").time())
    with db() as c:
        rows = c.execute(
            "SELECT start,end FROM events WHERE start < ? AND end > ? ORDER BY start",
            (we.strftime(FMT), ws.strftime(FMT)),
        ).fetchall()
    slots, cursor = [], ws
    for r in rows:
        s, e = parse_dt(r["start"]), parse_dt(r["end"])
        if s - cursor >= timedelta(minutes=duration_minutes):
            slots.append({"start": cursor.strftime("%H:%M"), "end": s.strftime("%H:%M")})
        cursor = max(cursor, e)
    if we - cursor >= timedelta(minutes=duration_minutes):
        slots.append({"start": cursor.strftime("%H:%M"), "end": we.strftime("%H:%M")})
    return {"date": str(d), "free_slots": slots}


def get_current_time():
    n = now()
    return {"now": n.strftime(FMT), "weekday": "一二三四五六日"[n.weekday()], "timezone": str(TZ)}


# ───────────────────────── 工具注册 ─────────────────────────
def _t(name, desc, props, required=()):
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": list(required)}}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
TAGS = {"type": "array", "items": S, "description": "标签列表，如 ['工作','想法']"}
DT = lambda d: {"type": "string", "description": d + "，格式 YYYY-MM-DD HH:MM"}

TOOLS = [
    _t("save_note", "保存一条新笔记。用户随口记录、想法、待办、摘录时使用。",
       {"content": S, "title": {**S, "description": "简短标题，自行概括"}, "tags": TAGS}, ["content"]),
    _t("search_notes", "按关键词（空格分隔）和/或标签检索笔记，按相关度排序。",
       {"query": S, "tag": S, "limit": I}),
    _t("list_notes", "列出最近的笔记，可按标签过滤。", {"tag": S, "limit": I}),
    _t("update_note", "修改笔记的内容/标题/标签（用于整理、合并、补充）。",
       {"id": S, "content": S, "title": S, "tags": TAGS}, ["id"]),
    _t("delete_note", "删除笔记。必须先征得用户确认，再传 confirmed=true。",
       {"id": S, "confirmed": B}, ["id"]),
    _t("add_event", "添加日程。未给 end 时用 duration_minutes（默认 60）。有冲突会返回冲突项，不会直接写入。",
       {"title": S, "start": DT("开始时间"), "end": DT("结束时间，可选"),
        "duration_minutes": I, "location": S, "notes": S, "force": B}, ["title", "start"]),
    _t("list_events", "查看日程。不传参数则返回今天起 7 天。",
       {"start_date": {**S, "description": "YYYY-MM-DD"}, "end_date": {**S, "description": "YYYY-MM-DD"}}),
    _t("update_event", "修改日程（改期、改标题等）。只改 start 时保持原时长。",
       {"id": I, "title": S, "start": DT("新开始时间"), "end": DT("新结束时间"),
        "location": S, "notes": S, "force": B}, ["id"]),
    _t("delete_event", "删除日程。必须先征得用户确认，再传 confirmed=true。",
       {"id": I, "confirmed": B}, ["id"]),
    _t("find_free_slots", "查找某天的空闲时间段，用于帮用户挑选合适时间。",
       {"date": {**S, "description": "YYYY-MM-DD"}, "duration_minutes": I,
        "day_start": {**S, "description": "默认 09:00"}, "day_end": {**S, "description": "默认 18:00"}}, ["date"]),
    _t("get_current_time", "获取当前日期时间。解析“明天/下周三”等相对时间前如不确定请调用。", {}),
]
TOOLS[-1]["cache_control"] = {"type": "ephemeral"}  # 工具定义很稳定，缓存以省钱提速

# 笔记后端：macOS 默认用 Apple 备忘录，其他系统用 SQLite（可用 NOTES_BACKEND=sqlite|apple 覆盖）
if os.getenv("NOTES_BACKEND", "apple" if sys.platform == "darwin" else "sqlite") == "apple":
    from notes_apple import save_note, search_notes, list_notes, update_note, delete_note  # noqa: F811

DISPATCH = {f.__name__: f for f in (
    save_note, search_notes, list_notes, update_note, delete_note, add_event,
    list_events, update_event, delete_event, find_free_slots, get_current_time)}


def run_tool(name, args):
    try:
        return DISPATCH[name](**args)
    except Exception as ex:  # 把错误交还给模型，让它自行纠正参数
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"}


# ───────────────────────── Agent 主循环 ─────────────────────────
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_prompt.md")


def system_prompt():
    """从 system_prompt.md 读取提示词，并替换占位符（改提示词不用动代码）。"""
    n = now()
    text = open(PROMPT_FILE, encoding="utf-8").read()
    for k, v in {
        "{{NOW}}": n.strftime(FMT),
        "{{WEEKDAY}}": "一二三四五六日"[n.weekday()],
        "{{TZ}}": str(TZ),
        "{{NOTES_FOLDER}}": os.getenv("NOTES_FOLDER", "AI助理"),
    }.items():
        text = text.replace(k, v)
    if DEMO:
        text += "\n当前为演示模式，笔记仅在本地示例库，日历同步是模拟操作。"
    return text


def chat_turn(client, messages):
    """处理一轮用户输入：循环调用模型，直到不再需要工具。"""
    if DEMO:
        return "演示模式不调用模型；请查看示例安排。"
    for _ in range(8):  # 防止死循环
        resp = client.messages.create(
            model=MODEL, max_tokens=1500, system=system_prompt(),
            tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                out = run_tool(b.name, b.input)
                print(f"  · {b.name}")
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False)})
        messages.append({"role": "user", "content": results})
    return "（操作步骤过多，已中止，请换种说法再试。）"


def trim(messages, keep=30):
    """简单的上下文裁剪：保留最近 keep 条，并确保从用户文本消息开始。"""
    if len(messages) <= keep:
        return messages
    cut = messages[-keep:]
    while cut and not (cut[0]["role"] == "user" and isinstance(cut[0]["content"], str)):
        cut = cut[1:]
    return cut


import organizer
sync_calendar = organizer.install(sys.modules[__name__])


def main():
    import anthropic
    client = anthropic.Anthropic()
    messages = []
    print("个人助理已就绪（输入 q 退出）。试试：“记一下：周五前把报销单交了” / “明天下午3点和老王开会” / “我这周有什么安排？”")
    while True:
        text = input("\n你：").strip()
        if text.lower() in ("q", "quit", "exit"):
            break
        if not text:
            continue
        messages.append({"role": "user", "content": text})
        try:
            print("助理：" + chat_turn(client, messages))
        except Exception as ex:
            print("请求失败：" + str(ex))
            print("请检查网络、API Key 或账户额度；已执行的操作不会自动回滚，请先查询再重试。")
            messages = []
        messages = trim(messages)


if __name__ == "__main__":
    main()
