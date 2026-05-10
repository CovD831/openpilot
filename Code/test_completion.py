#!/usr/bin/env python3
"""测试 prompt_toolkit 命令补全功能"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

# 系统命令列表
commands = [
    "/help", "/config", "/plan", "/execute", "/autopilot",
    "/task", "/report", "/memory", "/clear", "/exit", "/quit"
]

# 创建补全器
completer = WordCompleter(
    commands,
    ignore_case=True,
    sentence=True,
    match_middle=True,
)

# 创建历史记录
history = InMemoryHistory()

# 创建 session
session = PromptSession(
    completer=completer,
    history=history,
    enable_history_search=True,
    auto_suggest=AutoSuggestFromHistory(),
    complete_while_typing=True,
    complete_in_thread=True,
)

print("=" * 60)
print("OpenPilot 命令补全测试")
print("=" * 60)
print()
print("功能测试：")
print("  1. 输入 '/' 应该显示所有命令的下拉菜单")
print("  2. 输入 '/au' 应该过滤显示 /autopilot")
print("  3. 按 Tab 键补全命令")
print("  4. 按 ↑ ↓ 键浏览历史")
print("  5. 按 Ctrl+R 搜索历史")
print()
print("输入 'exit' 退出测试")
print("=" * 60)
print()

while True:
    try:
        user_input = session.prompt("test> ")

        if user_input.lower() in ['exit', 'quit']:
            print("测试结束")
            break

        print(f"你输入了: {user_input}")

    except (KeyboardInterrupt, EOFError):
        print("\n测试结束")
        break
