"""Run op0's TUI against a real pty, drive it with keystrokes, and dump the
rendered screen with pyte — so we SEE what the user sees."""
import fcntl
import os
import pty
import select
import struct
import sys
import termios
import time

import pyte

COLS, ROWS = 100, 30
fixture = sys.argv[1] if len(sys.argv) > 1 else "/tmp/op0-screen-check"
os.makedirs(fixture, exist_ok=True)
Path_ = fixture + "/answer.txt"
open(Path_, "w").write("VALUE = 555\n")

pid, fd = pty.fork()
if pid == 0:
    os.chdir(fixture)
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["OP0_PI_PROVIDER"] = os.environ.get("OP0_PI_PROVIDER", "deepseek")
    env["OP0_PI_MODEL"] = "deepseek-v4-flash"
    env["LINES"] = str(ROWS)
    env["COLUMNS"] = str(COLS)
    os.execve("/Users/abab/Developer/openpilot-l0/Code/.venv/bin/op0", ["op0"], env)

fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

screen = pyte.Screen(COLS, ROWS)
stream = pyte.Stream(screen)

def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                data = os.read(fd, 65536)
            except OSError:
                return False
            if not data:
                return False
            stream.feed(data.decode("utf-8", errors="replace"))
    return True

def dump(title):
    print(f"===== {title} =====")
    lines = screen.display
    for i, line in enumerate(lines):
        marker = "·" if line.strip() else " "
        print(f"{i:2d}{marker}|{line.rstrip()}")
    print()

# 1) boot
pump(4)
dump("BOOT (after 4s)")

# 2) submit a read task
os.write(fd, "读取 answer.txt 回答 VALUE 等于多少\r".encode())
pump(25)
dump("AFTER TASK (25s)")
os.write(fd, "/exit\r".encode())
pump(1)
try:
    os.kill(pid, 9)
except ProcessLookupError:
    pass
