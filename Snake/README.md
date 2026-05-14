# Snake

## Overview

在'/Users/yanning/Projects/openpilot/Snake'中做一个贪吃蛇

Recent Improvements:
- Add pause/resume functionality with a visual 'PAUSED' overlay when pressing the 'P' key during active gameplay. Pause freezes snake movement, resume restarts it. Pause is disallowed when game over, and game state remains unchanged.
- Fix the runtime error reported by the smoke test.
- Add a start screen state to main.py: display title and instructions on launch, transition to playing on any key or mouse click. Modify the game over flow so pressing a key returns to the start screen.
- Rewrite main.py using pygame to replace the Tkinter implementation, preserving all existing game states, controls, scoring, speed progression, and pause/restart/quit functionality.

## Requirements

- Python 3

## Setup

```bash
pip install pygame
```

## Run

```bash
python main.py
```

## Files

- `main.py`

## Troubleshooting

- If the run command fails because a package is missing, run the setup command first.
- If you use a virtual environment or Conda environment, activate it before running the project.
- Run commands from this project directory unless the command says otherwise.
- Terminal or GUI games should be run in a real interactive terminal/window, not from a captured non-interactive smoke test.
