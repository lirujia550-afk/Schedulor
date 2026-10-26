"""
Apple 备忘录后端（macOS 专用）：通过 osascript 调用 AppleScript 读写备忘录。
- 只操作一个专用文件夹（默认「AI助理」），不会碰你其他备忘录
- 删除 = 移到备忘录的「最近删除」，30 天内可恢复
- 备忘录没有对外的标签 API，所以标签写成笔记最后一行「标签：工作、待办」
首次运行时 macOS 会弹窗询问是否允许「终端/Python」控制「备忘录」，请点允许。
自检：python notes_apple.py
"""
import html
import os
import subprocess
import sys

FOLDER = os.getenv("NOTES_FOLDER", "AI助理")
US, RS = "\x1f", "\x1e"  # 字段分隔 / 记录分隔
TAG_PREFIX = "标签："

_LIST = f'''
on run argv
  set fname to item 1 of argv
  tell application "Notes"
    if not (exists folder fname) then make new folder with properties {{name:fname}}
    set f to folder fname
    set ids to id of every note of f
    set nms to name of every note of f
    set mds to modification date of every note of f
    set pts to plaintext of every note of f
    set out to ""
    repeat with i from 1 to count of ids
      set out to out & (item i of ids) & (ASCII character 31) & (item i of nms) & (ASCII character 31) & ((item i of mds) as string) & (ASCII character 31) & (item i of pts) & (ASCII character 30)
    end repeat
    return out
  end tell
end run
'''

_CREATE = '''
on run argv
  set fname to item 1 of argv
  set bodyHtml to item 2 of argv
  tell application "Notes"
    if not (exists folder fname) then make new folder with properties {name:fname}
    set n to make new note at folder fname with properties {body:bodyHtml}
    return id of n
  end tell
end run
'''

_UPDATE = '''
on run argv
  set nid to item 1 of argv
  set bodyHtml to item 2 of argv
  tell application "Notes"
    set n to note id nid
    set body of n to bodyHtml
    return id of n
  end tell
end run
'''

_DELETE = '''
on run argv
  set nid to item 1 of argv
  tell application "Notes" to delete note id nid
  return "ok"
end run
'''


def _osa(script, *args):
    if sys.platform != "darwin":
        raise RuntimeError("Apple 备忘录后端只能在 macOS 上运行；其他系统请设置 NOTES_BACKEND=sqlite")
    r = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(
            (r.stderr.strip() or "osascript 执行失败")
            + "｜若提示未授权：系统设置 → 隐私与安全性 → 自动化，允许终端控制「备忘录」"
        )
    return r.stdout.strip("\n")


def _body(title, content, tags):
    paras = "".join(f"<div>{html.escape(line) or '<br>'}</div>" for line in content.split("\n"))
    tag_line = f"<div>{TAG_PREFIX}{html.escape('、'.join(tags))}</div>" if tags else ""
    return f"<div><h1>{html.escape(title)}</h1></div>{paras}{tag_line}"


def _tags_list(tags):
    return [t.strip().lstrip("#") for t in (tags or []) if t.strip()]


def _load():
    raw = _osa(_LIST, FOLDER)
    notes = []
    for rec in filter(None, raw.split(RS)):
        parts = rec.strip("\n").split(US)
        if len(parts) < 4:
            continue
        nid, name, modified, plain = parts[0], parts[1], parts[2], US.join(parts[3:])
        lines = plain.split("\n")
        body = lines[1:] if lines and lines[0].strip() == name.strip() else lines
        tags = []
        if body and body[-1].startswith(TAG_PREFIX):
            tags = [t for t in body[-1][len(TAG_PREFIX):].split("、") if t]
            body = body[:-1]
        notes.append({"id": nid, "title": name, "content": "\n".join(body).strip(),
                      "tags": tags, "updated_at": modified})
    return notes


def _view(n, limit=800):
    return {**n, "content": n["content"][:limit], "tags": ",".join(n["tags"])}


# ───────────── 与 agent.py 中 SQLite 版同名同签名的工具函数 ─────────────
def save_note(content, title="", tags=None):
    tags = _tags_list(tags)
    title = (title or content.strip().split("\n")[0][:15]).strip() or "未命名"
    nid = _osa(_CREATE, FOLDER, _body(title, content, tags))
    return {"ok": True, "id": nid, "title": title}


def search_notes(query="", tag="", limit=10):
    kws = [k.lower() for k in query.split() if k]
    scored = []
    for n in _load():
        if tag and tag.lstrip("#") not in n["tags"]:
            continue
        text = f'{n["title"]} {n["content"]} {" ".join(n["tags"])}'.lower()
        score = sum(k in text for k in kws) if kws else 1
        if score:
            scored.append((score, n))
    scored.sort(key=lambda x: -x[0])
    return {"count": len(scored), "notes": [_view(n) for _, n in scored[:limit]]}


def list_notes(tag="", limit=20):
    return search_notes("", tag, limit)


def update_note(id, content=None, title=None, tags=None):
    cur = next((n for n in _load() if n["id"] == str(id)), None)
    if not cur:
        return {"ok": False, "error": f"笔记 {id} 不存在"}
    new_tags = _tags_list(tags) if tags is not None else cur["tags"]
    body = _body(title if title is not None else cur["title"],
                 content if content is not None else cur["content"], new_tags)
    _osa(_UPDATE, str(id), body)
    return {"ok": True}


def delete_note(id, confirmed=False):
    if not confirmed:
        return {"ok": False, "need_confirm": True, "hint": "请先向用户确认后再以 confirmed=true 调用"}
    if not any(n["id"] == str(id) for n in _load()):
        return {"ok": False, "error": "笔记不在专用文件夹中"}
    _osa(_DELETE, str(id))
    return {"ok": True, "note": "已移到备忘录的「最近删除」，30 天内可恢复"}


if __name__ == "__main__":
    print("1) 写入测试笔记…")
    r = save_note("这是自检内容\n第二行", "自检笔记", ["测试"])
    print(r)
    print("2) 读取…", search_notes("自检")["count"], "条命中")
    print("3) 修改…", update_note(r["id"], content="已修改"))
    print("4) 删除…", delete_note(r["id"], confirmed=True))
    print("自检完成：去备忘录 App 的「%s」文件夹和「最近删除」看看。" % FOLDER)
