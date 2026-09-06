"""op0: minimal Pi-runtime closed loop (L0 clean base).

Only the execution base lives here: one Pi subprocess, one read-only tool,
one REPL, one JSONL trajectory. Admission (L1), durable receipts (L2) and
recovery (L3) are added on top later — never by importing the legacy tree.
"""

__version__ = "0.1.0"
