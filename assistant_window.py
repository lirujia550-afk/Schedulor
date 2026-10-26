"""Native Tk chat window using the existing personal assistant backend."""
import contextlib
import io
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import anthropic
import agent
from runtime import DATA_DIR, DEMO

ROOT = Path(__file__).resolve().parent
SETTINGS = DATA_DIR / '.window-settings.json'


def load_settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def save_settings(key, remember):
    if not remember:
        SETTINGS.unlink(missing_ok=True)
        return
    temp = SETTINGS.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'api_key':key}, f)
    temp.replace(SETTINGS)


def friendly_error(error):
    status = getattr(error, 'status_code', None)
    if status == 401:
        return '连接凭证无效，请在设置中更新后重试。'
    if status == 429:
        return '请求受限或额度不足，请稍后再试并检查 API 账户额度。'
    if status in (403,404):
        return '账户没有当前模型的访问权限，或模型不可用。请检查 API 账户。'
    if isinstance(error, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return '连接模型失败，请检查网络后重试。'
    return '处理失败（' + type(error).__name__ + '）。请检查网络及日历/备忘录授权。'


class Conversation:
    def __init__(self):
        self.messages = []

    def reply(self, key, text):
        self.messages.append({'role':'user', 'content':text})
        try:
            with anthropic.Anthropic(api_key=key, timeout=90, max_retries=1) as client:
                # Tool input may contain private note contents; keep it out of app logs.
                with contextlib.redirect_stdout(io.StringIO()):
                    answer = agent.chat_turn(client, self.messages)
            self.messages = agent.trim(self.messages)
            return answer or '这次没有返回回复，请先查询保存结果。'
        except Exception:
            # A failed turn may contain incomplete tool calls. Start a clean history.
            self.messages = []
            raise


class Window:
    def __init__(self, root):
        self.root=root; self.busy=False; self.events=queue.Queue()
        self.conversation=Conversation(); config=load_settings()
        self.key=tk.StringVar(value=config.get('api_key') or os.getenv('ANTHROPIC_API_KEY',''))
        self.remember=tk.BooleanVar(value=bool(config.get('api_key')))
        self.buttons=[]; self.settings_window=None
        root.title('Schedulor · 演示' if DEMO else 'Schedulor');root.geometry('1000x720');root.minsize(850,650)
        root.configure(bg='#f4f5f9');root.protocol('WM_DELETE_WINDOW',self.close)
        style=ttk.Style();style.configure('Treeview',rowheight=38,font=('Helvetica',13))
        style.configure('Treeview.Heading',font=('Helvetica',12,'bold'))
        sidebar=tk.Frame(root,bg='#20283e',width=185);sidebar.pack(side='left',fill='y');sidebar.pack_propagate(False)
        tk.Label(sidebar,text='S',fg='white',bg='#6558e8',font=('Helvetica',30,'bold'),width=3,pady=8).pack(anchor='w',padx=22,pady=(30,12))
        tk.Label(sidebar,text='Schedulor',fg='white',bg='#20283e',font=('Helvetica',20,'bold')).pack(anchor='w',padx=22)
        tk.Label(sidebar,text='把安排变得简单',fg='#aeb7ce',bg='#20283e',font=('Helvetica',11)).pack(anchor='w',padx=22,pady=(8,30))
        self.nav={}
        for name in ['概览','聊天助理','待办事项','日程','笔记']:
            btn=tk.Label(sidebar,text=name,anchor='w',bg='#20283e',fg='#d8dded',font=('Helvetica',14),padx=20,pady=12,cursor='hand2')
            btn.bind('<Button-1>',lambda e,n=name:self.show(n))
            btn.pack(fill='x',padx=12,pady=3);self.nav[name]=btn
        settings_link=tk.Label(sidebar,text='设置',bg='#303a53',fg='white',font=('Helvetica',13),pady=10,cursor='hand2')
        settings_link.pack(side='bottom',fill='x',padx=18,pady=22);settings_link.bind('<Button-1>',lambda e:self.settings())
        self.main=tk.Frame(root,bg='#f4f5f9');self.main.pack(side='left',fill='both',expand=True,padx=26,pady=25)
        head=tk.Frame(self.main,bg='#f4f5f9');head.pack(fill='x')
        self.heading=tk.StringVar(value='概览')
        tk.Label(head,textvariable=self.heading,bg='#f4f5f9',fg='#20283e',font=('Helvetica',25,'bold')).pack(side='left')
        tk.Label(head,text=agent.now().strftime('%m月%d日')+' · 悉尼',bg='#f4f5f9',fg='#7d8393',font=('Helvetica',12)).pack(side='right')
        self.status=tk.StringVar(value='就绪')
        ttk.Label(self.main,textvariable=self.status).pack(side='bottom',anchor='w',pady=(12,0))
        self.body=tk.Frame(self.main,bg='#f4f5f9');self.body.pack(fill='both',expand=True,pady=(20,0))
        self.views={}
        for name in self.nav:self.views[name]=tk.Frame(self.body,bg='#f4f5f9')
        home=self.views['概览']
        tk.Label(home,text='今天，从一件事开始。',bg='#f4f5f9',fg='#777f91',font=('Helvetica',14)).pack(anchor='w',pady=(0,18))
        cards=tk.Frame(home,bg='#f4f5f9');cards.pack(fill='x')
        self.stats=[]
        for title in ['今日待办','今日日程','未完成待办']:
            card=tk.Frame(cards,bg='white',padx=20,pady=18);card.pack(side='left',fill='x',expand=True,padx=(0,10))
            tk.Label(card,text=title,bg='white',fg='#7c8190',font=('Helvetica',12)).pack(anchor='w')
            value=tk.StringVar(value='—');self.stats.append(value)
            tk.Label(card,textvariable=value,bg='white',fg='#6558e8',font=('Helvetica',30,'bold')).pack(anchor='w',pady=(8,0))
        tk.Label(home,text='接下来的安排',bg='#f4f5f9',fg='#20283e',font=('Helvetica',17,'bold')).pack(anchor='w',pady=(25,12))
        self.home_tree=self.tree(home,('时间','事项','类型'))
        row=tk.Frame(home,bg='#f4f5f9');row.pack(fill='x',pady=(14,0))
        ttk.Button(row,text='＋ 添加安排',command=lambda:self.show('聊天助理')).pack(side='left')
        ttk.Button(row,text='刷新',command=self.reload).pack(side='right')
        tasks=self.views['待办事项'];self.task_tree=self.tree(tasks,('截止时间','待办事项','状态'))
        row=tk.Frame(tasks,bg='#f4f5f9');row.pack(fill='x',pady=12)
        complete=ttk.Button(row,text='标记所选待办已完成',command=self.complete_selected);complete.pack(side='left');self.buttons.append(complete)
        ttk.Button(row,text='＋ 添加待办',command=lambda:self.show('聊天助理')).pack(side='right')
        self.event_tree=self.tree(self.views['日程'],('开始时间','结束时间','日程'))
        notes=self.views['笔记'];self.note_tree=self.tree(notes,('标题','标签'))
        self.note_tree.bind('<<TreeviewSelect>>',self.preview_note)
        self.note_preview=tk.Text(notes,height=5,wrap='word',state='disabled',font=('Helvetica',13),bg='white',relief='flat',padx=12,pady=12)
        self.note_preview.pack(fill='x',pady=(12,0));self.notes={}
        chat=self.views['聊天助理'];transcript=tk.Frame(chat);transcript.pack(fill='both',expand=True)
        self.chat=tk.Text(transcript,height=10,width=1,wrap='word',state='disabled',font=('Helvetica',14),padx=16,pady=14,relief='flat',background='white')
        scroll=ttk.Scrollbar(transcript,command=self.chat.yview);self.chat.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.chat.pack(fill='both',expand=True)
        for role,color in [('user','#6558e8'),('assistant','#252b3d'),('system','#7c8190')]:self.chat.tag_configure(role,foreground=color,spacing1=12,spacing3=8)
        shortcuts=tk.Frame(chat,bg='#f4f5f9');shortcuts.pack(fill='x',pady=12)
        for label,action in [('今日安排',lambda:self.send('查询我今天的待办和日程。')),('本周安排',lambda:self.send('查询我本周的待办和日程。')),('同步日历',self.sync),('新对话',self.new_chat)]:
            btn=ttk.Button(shortcuts,text=label,command=action);btn.pack(side='left',padx=(0,7));self.buttons.append(btn)
        tk.Label(chat,text='说说你的安排，例如：周五下午一点前提交作业',bg='#f4f5f9',fg='#7c8190',font=('Helvetica',12)).pack(anchor='w',pady=(0,7))
        bottom=tk.Frame(chat,bg='#f4f5f9');bottom.pack(fill='x')
        self.input=tk.Text(bottom,height=3,wrap='word',font=('Helvetica',14),padx=12,pady=10,bg='white',relief='flat',highlightthickness=1,highlightbackground='#dfe2ed')
        self.input.pack(side='left',fill='x',expand=True)
        send=ttk.Button(bottom,text='发送',command=self.send);send.pack(side='right',padx=(10,0));self.buttons.append(send)
        self.input.bind('<Return>',self.enter);self.input.bind('<Shift-Return>',lambda e:None);self.input.bind('<Command-Return>',self.enter)
        self.append('system','欢迎来到 Schedulor。输入安排即可记录；没有安排的日期不会生成汇总。')
        for number,name in enumerate(self.nav,1):
            root.bind('<Command-Key-'+str(number)+'>',lambda e,n=name:self.show(n))
        self.show('概览');root.after(100,self.poll)

    def tree(self,parent,columns):
        frame=tk.Frame(parent,bg='white');frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame,columns=columns,show='headings',selectmode='browse',height=7)
        for col in columns:tree.heading(col,text=col);tree.column(col,width=170,stretch=True)
        sb=ttk.Scrollbar(frame,command=tree.yview);tree.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        return tree

    def show(self,name):
        for frame in self.views.values():frame.pack_forget()
        self.views[name].pack(fill='both',expand=True);self.heading.set(name)
        for n,b in self.nav.items():b.configure(bg='#39435e' if n==name else '#20283e')
        if name=='笔记':self.load_notes()
        elif name!='聊天助理':self.reload()
        else:self.input.focus_set()

    def reload(self):
        from datetime import timedelta
        try:
            with agent.db() as c:
                tasks=[dict(r) for r in c.execute('SELECT * FROM tasks WHERE completed=0 ORDER BY due')]
                events=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY start')]
            n=agent.now();today=n.strftime('%Y-%m-%d')
            for t in [self.task_tree,self.event_tree,self.home_tree]:t.delete(*t.get_children())
            for r in tasks:self.task_tree.insert('', 'end',iid=str(r['id']),values=(r['due'],r['title'],'逾期' if r['due'][:10]<today else '待完成'))
            upcoming=[]
            for r in events:
                if agent.parse_dt(r['end'])>=n:
                    self.event_tree.insert('','end',values=(r['start'],r['end'],r['title']))
                    upcoming.append((r['start'],r['title'],'日程'))
            upcoming += [(r['due'],r['title'],'待办') for r in tasks if r['due'][:10]>=today]
            for item in sorted(upcoming)[:12]:self.home_tree.insert('','end',values=item)
            if not upcoming:self.home_tree.insert('','end',values=('','暂时没有安排，去聊天添加一件事吧',''))
            self.stats[0].set(str(sum(r['due'][:10]==today for r in tasks)))
            self.stats[1].set(str(sum(agent.parse_dt(r['start'])<n.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1) and agent.parse_dt(r['end'])>n.replace(hour=0,minute=0,second=0,microsecond=0) for r in events)))
            self.stats[2].set(str(len(tasks)))
        except Exception:self.status.set('读取安排失败，请稍后刷新。')

    def load_notes(self):
        if self.busy:return
        self.set_busy(True)
        def work():
            try:self.events.put(('notes',agent.list_notes(limit=100).get('notes',[])))
            except Exception:self.events.put(('system','无法读取笔记，请检查备忘录授权。'))
        threading.Thread(target=work,daemon=True).start()

    def preview_note(self,event):
        selected=self.note_tree.selection()
        if not selected:return
        note=self.notes.get(selected[0],{})
        self.note_preview.configure(state='normal');self.note_preview.delete('1.0','end')
        self.note_preview.insert('end',note.get('content',''));self.note_preview.configure(state='disabled')

    def complete_selected(self):
        if self.busy:return
        selected=self.task_tree.selection()
        if not selected:
            messagebox.showinfo('待办事项','请先选择一条待办。');return
        ident=int(selected[0]);self.set_busy(True)
        def work():
            try:
                r=agent.DISPATCH['complete_task'](ident)
                text='已标记完成。' if r.get('ok') else '未能标记完成。'
                if r.get('calendar_synced') is False:text+='日历尚未同步，请重试同步日历。'
                self.events.put(('system',text))
            except Exception:self.events.put(('system','操作未完成，请刷新确认状态。'))
        threading.Thread(target=work,daemon=True).start()

    def settings(self):
        if self.settings_window and self.settings_window.winfo_exists():self.settings_window.lift();return
        dialog=tk.Toplevel(self.root);self.settings_window=dialog;dialog.title('Schedulor · 设置');dialog.geometry('500x260');dialog.resizable(False,False)
        frame=ttk.Frame(dialog,padding=22);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='模型连接',font=('Helvetica',17,'bold')).pack(anchor='w',pady=(0,15))
        ttk.Label(frame,text='Anthropic API Key').pack(anchor='w')
        entry=ttk.Entry(frame,textvariable=self.key,show='•');entry.pack(fill='x',pady=8)
        ttk.Checkbutton(frame,text='在此 Mac 上记住',variable=self.remember).pack(anchor='w')
        ttk.Label(frame,text='凭证仅保存在本机配置文件。聊天内容会发送到 Anthropic。',wraplength=440).pack(anchor='w',pady=10)
        ttk.Button(frame,text='保存并关闭',command=lambda:(self.persist(),dialog.destroy())).pack(anchor='e')
        entry.focus_set()

    def append(self, role, text):
        names={'user':'你','assistant':'助理','system':'提示'}
        self.chat.configure(state='normal')
        self.chat.insert('end',names[role]+'：'+text+'\n',role)
        self.chat.configure(state='disabled');self.chat.see('end')

    def enter(self,event):
        self.send()
        return 'break'

    def set_busy(self,busy):
        self.busy=busy
        for b in self.buttons:b.configure(state='disabled' if busy else 'normal')
        self.status.set('正在处理，请稍候…' if busy else '就绪 · 回车发送，Shift＋回车换行')

    def persist(self):
        try:save_settings(self.key.get().strip(),self.remember.get())
        except OSError:
            self.append('system','无法保存 Key 设置，本次仍可使用；下次启动可能需要重新输入。')

    def send(self,text=None):
        if self.busy:return
        text=text if text is not None else self.input.get('1.0','end').strip()
        if not text:return
        key=self.key.get().strip()
        if DEMO:
            self.append('system','演示模式仅展示示例数据，不调用模型、不修改真实日历。请退出后按 README 的真实模式配置。');return
        if not key:
            self.append('system','请先在设置中配置模型连接。')
            self.settings();return
        self.persist()
        self.input.delete('1.0','end')
        self.append('user',text);self.set_busy(True)
        def work():
            try:self.events.put(('assistant',self.conversation.reply(key,text)))
            except Exception as error:
                self.events.put(('system',friendly_error(error)+'\n部分操作可能已经保存，请先查询结果再重复添加。'))
        threading.Thread(target=work,daemon=True).start()

    def sync(self):
        if self.busy:return
        self.set_busy(True)
        def work():
            try:
                r=agent.sync_calendar()
                if r['ok']:text='演示同步完成，未修改真实日历。' if DEMO else '日历同步完成，多余的空白汇总已按当前规则清理。'
                else:text='日历同步尚未完成。请检查系统设置 → 隐私与安全性 → 自动化中的日历权限；本地数据保留，可以再次重试。'
                self.events.put(('system',text))
            except Exception:self.events.put(('system','同步失败，请检查日历授权后重试。'))
        threading.Thread(target=work,daemon=True).start()

    def new_chat(self):
        if self.busy:return
        self.conversation.messages=[]
        self.chat.configure(state='normal');self.chat.delete('1.0','end');self.chat.configure(state='disabled')
        self.append('system','已开始新对话，保存过的笔记、待办和日程仍在。')

    def poll(self):
        try:
            while True:
                role,text=self.events.get_nowait()
                if role=='notes':
                    self.note_tree.delete(*self.note_tree.get_children());self.notes={}
                    for i,n in enumerate(text):
                        key=str(i);self.notes[key]=n;self.note_tree.insert('','end',iid=key,values=(n.get('title',''),n.get('tags','')))
                else:self.append(role,text)
                self.set_busy(False);self.reload()
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('正在处理','请等待本次操作结束再关闭，避免不知道哪些事项已保存。')
            return
        self.persist();self.root.destroy()


if __name__=='__main__':
    os.chdir(ROOT)
    import fcntl
    lock = open(DATA_DIR / '.window.lock', 'w')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: raise SystemExit(0)
    root=tk.Tk();root.tk.call('tk','appname','Schedulor');window=Window(root)
    root.mainloop()
