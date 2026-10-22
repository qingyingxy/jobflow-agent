from __future__ import annotations

import json

import pytest

from scripts import run_core_v35_evaluation as runner


def test_v35_runner_preflight_uses_frozen_transport_settings(monkeypatch) -> None:
    for key in runner.RUN_ENVIRONMENT:
        monkeypatch.setenv(key, "restore-after-test")
    runner._configure_environment()

    summary = runner._client_summary()

    assert summary["thinking_mode"] == "disabled"
    assert summary["model_retries"] == 0
    assert summary["parser_retries"] == 0


def test_v35_runner_rejects_failed_canary(tmp_path, monkeypatch) -> None:
    canary = tmp_path / "canary.json"
    canary.write_text(
        json.dumps(
            {
                "prediction_failure_count": 1,
                "predictions": [{"failure_code": "model_response_invalid"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "CANARY_OUTPUT", canary)

    with pytest.raises(SystemExit, match="canary did not succeed"):
        runner._require_canary_success()
