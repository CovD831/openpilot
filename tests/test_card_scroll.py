"""Approval card fixed-height scrolling: a long command/diff must never push
the options block off-screen (found during the real flask-4992 run). The
header and options stay always visible; the body scrolls with PgUp/PgDn."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0 import ui  # noqa: E402
from op0.admission import AdmissionGrant, AdmissionRegistry, Proposal  # noqa: E402


def _proposal(tmp_path, command: str) -> Proposal:
    registry = AdmissionRegistry(str(tmp_path))
    return registry.propose_command("goal", command)


def test_long_command_scrolls_inside_card(tmp_path):
    proposal = _proposal(tmp_path, "python -m pytest " + "tests/test_module_very_long_name.py " * 30)
    full = ui.render_proposal_to_str(proposal, selected=0)
    capped = ui.render_proposal_to_str(proposal, selected=0, body_height=2, scroll=0)
    full_lines = full.count("\n") + 1
    capped_lines = capped.count("\n") + 1
    assert capped_lines <= full_lines  # the capped render is shorter
    assert "Yes to all" in capped  # options are ALWAYS in the rendered card
    assert "PgDn" in capped  # the scroll indicator shows


def test_scroll_window_moves_and_clamps(tmp_path):
    proposal = _proposal(tmp_path, "echo " + "x" * 200)
    body = ui.render_proposal_to_str(proposal, selected=0, body_height=2, scroll=0)
    middle = ui.render_proposal_to_str(proposal, selected=0, body_height=2, scroll=4)
    assert body != middle  # the window moved
    # clamped far beyond the end: same as the last page, options still visible
    far = ui.render_proposal_to_str(proposal, selected=0, body_height=2, scroll=10_000)
    assert "Yes to all" in far
    assert "PgUp" in far and "PgDn" not in far  # nothing below: indicator flips


def test_short_body_is_untouched_by_scroll_logic(tmp_path):
    proposal = _proposal(tmp_path, "echo hi")
    plain = ui.render_proposal_to_str(proposal, selected=0)
    capped = ui.render_proposal_to_str(proposal, selected=0, body_height=10)
    # a short body fits: no scroll indicators, same content
    assert "PgDn" not in capped and "PgUp" not in capped
    assert capped == plain
