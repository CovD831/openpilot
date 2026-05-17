# Snake

## Overview

帮我在'/Users/yanning/Projects/openpilot/Snake'中写一个贪吃蛇

Recent Improvements:
- Rewrite main.py to use pygame: replace tkinter with pygame for the game window, game loop, event handling (arrow keys, R to restart, Q to quit), snake rendering (green body, yellow head), red food square, score display, and game-over overlay with final score. No tkinter or curses imports.
- Fix the validation failure: Fix the runtime error reported by the smoke test.
- Fix the validation failure: Fix the runtime error reported by the smoke test.
- Fix the validation failure: Fix the runtime error reported by the smoke test.

## Requirements

- Virtual Environment: .venv
- Python Executable: /Users/yanning/Projects/openpilot/Snake/.venv/bin/python
- Python Version: 3.11.15
- Dependencies: pygame

## Setup

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install pygame
```

```bash
.venv/bin/python --version
```

## Run

```bash
.venv/bin/python main.py
```

## Files

- `main.py`

## Troubleshooting

- If the run command fails because a package is missing, run the setup command first.
- If you use a virtual environment or Conda environment, activate it before running the project.
- Run commands from this project directory unless the command says otherwise.
- Terminal or GUI games should be run in a real interactive terminal/window, not from a captured non-interactive smoke test.
