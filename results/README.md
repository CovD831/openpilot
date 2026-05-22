# results

## Overview

帮我在'/Users/yanning/Projects/openpilot/results'中做一个贪吃蛇

Recent Improvements:
- Rewrite main.py to use pygame exclusively, implementing the complete snake game with game-over screen, score display, and restart/quit functionality. Remove all tkinter imports and logic.
- Implement high score persistence and display in main.py: add functions to load/save high score from/to a file (highscore.txt) in the project directory, load high score on game start, update and save when current score exceeds high score, and display both current and high score on the game over screen.
- Modify main.py to increase game speed (FPS) by 1 every 5 points scored, and reset speed to base (10 FPS) when the game restarts.

## Requirements

- Virtual Environment: .venv
- Python Executable: /Users/yanning/Projects/openpilot/results/.venv/bin/python
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
