from __future__ import annotations

from autonomous_iteration.engines.pi_canary import PiCanaryMode, PiCanaryResult


def test_pi_canary_result_contract_excludes_credentials() -> None:
    result = PiCanaryResult(
        provider="deepseek",
        model="deepseek-v4-flash",
        mode=PiCanaryMode.READ_ONLY,
        passed=True,
        engine_state="stopped",
        run_status="blocked",
        marker_present=True,
    )

    payload = result.model_dump(mode="json")
    encoded = result.model_dump_json()

    assert set(payload) == {
        "provider",
        "model",
        "mode",
        "passed",
        "engine_state",
        "run_status",
        "marker_present",
        "target_updated",
        "mutation_receipt",
        "validation_completed",
        "verification_recorded",
        "credential_marker_persisted",
        "event_count",
        "tool_sequence",
        "mutation_requested",
        "validation_passed",
        "verification_status",
        "resume_attempt_recorded",
        "reconciliation_completed",
    }
    assert "api_key" not in encoded
    assert "secret" not in encoded
