# OpenPilot (package)

This directory is the `openpilot` Python package. For the full project overview,
architecture, setup, and handover notes, see the **[top-level README](../README.md)**.

```bash
pip install -r requirements.txt
pip install -e .
openpilot run
```

- `src/` — source code (`ui`, `autonomous_iteration`, `agent_generator`, `tools`,
  `metadata`, `core`, `memory`, `utils`).
- `tests/` — pytest suite (`pytest`).
- `pyproject.toml` — package metadata and the `openpilot` CLI entry point.
