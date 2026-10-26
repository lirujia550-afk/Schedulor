# Schedulor

**A macOS AI assistant for notes, tasks and Apple Calendar.**

把“周五下午一点前交作业”变成有截止日期的待办，把“明晚七点开会”变成日程。Schedulor 是一个使用 Python、Claude API、SQLite 和 AppleScript 开发的个人桌面项目，探索自然语言如何连接到真实的笔记和日历操作。

![Schedulor 界面示意，使用虚构数据](docs/interface.svg)

*界面示意：使用虚构任务展示页面布局，不含个人记录。*

## 功能

- **概览**：今日待办、今日日程和接下来的安排。
- **聊天助理**：通过自然语言记录、查找和修改事项。
- **待办管理**：保存截止时间、查看未完成项、标记完成。
- **Apple 集成**：在专用文件夹中读写备忘录，向专用日历单向同步事项。
- **日/周汇总**：有安排的日期才生成09:00摘要，周一按需加入本周汇总。
- **同步重试**：本地保存与同步结果分别返回；失败后可以重试同步。
- **设置窗口**：连接凭证不出现在主面板。

这是学习与个人使用原型，不是已完成安全审计的商业产品。仓库不包含个人数据、凭证、虚拟环境或预编译应用。

## 快速体验：不需要 API Key

需要 macOS、Python 3.11+，以及带 Tk 支持的 Python。安装依赖仍需要联网。

```bash
git clone https://github.com/lirujia550-afk/Schedulor.git
cd Schedulor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m tkinter
```

最后一行用于检查 Tk，关闭测试窗口后执行：

```bash
python scripts/create_demo.py
SCHEDULOR_DEMO=1 python assistant_window.py
```

演示模式只加载虚构示例，禁用模型调用，笔记使用隔离的 SQLite 库，日历同步为模拟操作。它可以展示页面和待办完成流程，不会访问你的真实备忘录或日历。

## 真实使用

退出演示窗口，在 Apple 日历的 **iCloud 账户**下手动创建唯一的「AI助理」日历，再执行：

```bash
python assistant_window.py
```

在左下角 **设置** 输入自己的 Anthropic API Key。使用 API 可能产生费用；模型默认值继承自项目原型，可通过 `AGENT_MODEL` 设置为自己账户可用的模型 ID。

```bash
export AGENT_MODEL="你的账户可用的模型ID"
export AGENT_TZ="Australia/Sydney"
python assistant_window.py
```

首次操作时，请按 macOS 提示允许启动程序控制备忘录和日历。笔记默认放在「AI助理」文件夹；手机需使用同一 Apple 账户，开启 iCloud 日历和日历通知。

`.env.example` 仅为配置参考，程序不会自动加载它。可配置 `NOTES_FOLDER`、`AGENT_CALENDAR`、`AGENT_TZ`、`AGENT_MODEL` 和 `SCHEDULOR_DATA_DIR`。

## 桌面启动与后台汇总

生成本机双击启动器：

```bash
python scripts/build_app.py
```

打开 `dist/Schedulor.app`。该启动器依赖当前源码路径和虚拟环境，不是可复制到其他 Mac 的独立发行包。

后台更新是可选操作，窗口默认不会注册或改动已有系统服务：

```bash
python refresh.py
python scripts/background.py install
```

它在登录时及每天08:45更新未来约35天的摘要；09:00由日历提醒。系统时区应与配置时区一致。停用：

```bash
python scripts/background.py remove
```

Mac 关机或睡眠时不会更新内容；手机仍可触发已同步的提醒。停用后台不会删除已经写入日历的摘要。

## 项目结构

```text
assistant_window.py   桌面界面与后台线程
agent.py              模型对话、工具定义、笔记及日程逻辑
organizer.py          结构化待办、同步队列、日/周摘要
notes_apple.py        Apple 备忘录桥接
calendar_apple.py     Apple 日历桥接
runtime.py            演示隔离与数据目录
system_prompt.md     助理行为和工具使用规则
refresh.py            不依赖模型的汇总更新入口
scripts/              演示数据、本机启动器及可选后台配置
tests/                无真实 API 调用的自动化测试
```

交互流程：用户输入 → Claude 理解并选择工具 → Python 校验和保存 → AppleScript 写入日历/备忘录 → iCloud 同步。模型文字回复不等同于操作成功，工具结果决定同步状态。

## 开发过程与个人贡献

我负责确定学习场景、需求优先级、运行测试、体验反馈和产品决策。Codex 辅助编写代码、分析错误、补充验证并迭代界面；Claude 作为应用运行时的语言理解模型。选择支持工具调用的模型，是为了让自然语言连接到可执行操作，项目未做正式的多模型性能比较。

迭代中主要解决了三个问题：将普通作业笔记升级为有截止日期和完成状态的待办；将本地日程同步到 Apple 日历；修正空白日期也生成摘要、逾期事项在后续日期重复显示的问题。随后把终端原型整理成桌面窗口，并将凭证配置移到设置页。

ImageGen 曾用于探索图标候选，尚未选定最终版本，本仓库未包含这些候选图。

## 验证

```bash
python -m unittest discover -s tests -v
```

测试使用临时数据库和模拟日历桥接，不访问真实账户。覆盖空日期不生成摘要、周一汇总、完成待办后的摘要清理、同步失败重试、冲突检查、删除确认及演示隔离。

个人 Mac 上曾验证窗口启动、数据库迁移和日历同步。真实模型访问权限、macOS 自动化授权和 iPhone 通知需要在使用者设备上单独验证；没有进行量化用户研究。

## 数据与当前限制

真实数据默认保存在 `~/Library/Application Support/Schedulor/`，演示数据在相邻的 `Schedulor-Demo/`。勾选“在此 Mac 上记住”时，Key 保存到权限为0600的本地配置文件，**并非钥匙串加密存储**。不要公开整个数据目录。聊天和工具返回的相关内容会发送给 Anthropic 处理。

应用按专用文件夹和日历限制操作范围，但 AppleScript 授权本身不是文件夹级隔离。删除确认依赖界面操作和助理规则，不应视为独立的安全授权机制。

日历是从本地数据库到 Apple 日历的单向同步，外部修改不会写回本地。冲突检测只覆盖助理记录的日程，不覆盖其他课表。待办以全天事项展示；明确的截止时刻保存在本地记录和摘要中。重复发送新增指令仍可能创建重复待办。会话历史在关闭窗口后清空，已保存的记录会保留。

目前主要面向 macOS；Linux/Windows 的真实 Apple 集成不受支持。窗口可能在系统菜单或 Dock 中显示为 Python。正式发行前仍需改进打包、凭证存储、同步并发和数据恢复体验。
