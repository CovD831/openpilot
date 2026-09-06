# op0 — L0 clean base

Minimal Pi-runtime execution base: one Pi subprocess, one read-only tool,
one REPL, one JSONL trajectory. Grows by adding layers (L1 admission,
L2 evidence, L3 recovery) — never by importing the legacy tree.

    Code/src/op0        Python side (see L0_CLEAN_BASE_PLAN_CN.md)
    Code/pi_sidecar     Pi RPC runtime (node, pinned @0.84.3)
    accept_l0.py        six-gate acceptance (environment / cold start /
                        read-only loop / trajectory / line budget / no-legacy-import)

    uv venv Code/.venv && uv pip install --python Code/.venv/bin/python -e Code
    cd Code/pi_sidecar && npm ci
    python3 accept_l0.py --base-root .
