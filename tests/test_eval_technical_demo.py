"""Transport failures must stop sequential probes without a live service."""

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/eval_technical_demo.py"


@pytest.fixture
def probe(monkeypatch):
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setitem(sys.modules, "gradio_client", SimpleNamespace(Client=factory))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=Mock()))
    monkeypatch.setitem(sys.modules, "bikefinder_rag.db.client", SimpleNamespace(get_connection=MagicMock()))
    monkeypatch.setitem(sys.modules, "bikefinder_rag.agent.tools", SimpleNamespace(get_bike_details=Mock(return_value=[])))
    monkeypatch.delenv("HF_HUB_DISABLE_TELEMETRY", raising=False)
    spec = importlib.util.spec_from_file_location("technical_demo_probe_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.subprocess, "check_output", Mock(return_value="fixture-commit\n"))
    response = Mock()
    response.json.return_value = {"fixture": True}
    monkeypatch.setattr(module.requests, "get", Mock(return_value=response))
    return module, factory, client


@pytest.mark.parametrize("failure", [TimeoutError("client wait elapsed"), RuntimeError("transport disconnected")])
def test_failed_case_is_recorded_closes_client_and_never_submits_the_next_case(probe, monkeypatch, tmp_path, failure):
    module, factory, client = probe
    job = Mock()
    job.result.side_effect = failure
    job.cancel.return_value = True
    client.submit.return_value = job
    output = tmp_path / "probe.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--case", "missing_year", "--case", "reviews_deferred",
                                    "--gradio-timeout-seconds", "17.5", "--output", str(output)])

    module.main()

    report = json.loads(output.read_text())
    assert len(report["cases"]) == 1
    assert report["cases"][0]["api_error"] == f"{type(failure).__name__}: {failure}"
    assert report["stopped_after_api_error"] == "missing_year"
    assert report["unrun_cases"] == ["reviews_deferred"]
    assert report["cases"][0]["cancellation"] == {
        "attempted": True, "accepted": True, "server_stop_verified": False,
    }
    assert any("does not prove" in limitation for limitation in report["limitations"])
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert factory.call_count == client.submit.call_count == 1
    assert factory.call_args.kwargs["analytics_enabled"] is False
    assert factory.call_args.kwargs["httpx_kwargs"]["timeout"] == 30.0
    job.result.assert_called_once_with(timeout=17.5)
    client.close.assert_called_once_with()


def test_preflight_api_failure_is_reported_before_any_case_is_submitted(probe, monkeypatch, tmp_path):
    module, factory, _ = probe
    module.requests.get.side_effect = RuntimeError("metadata endpoint unavailable")
    output = tmp_path / "probe.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--case", "missing_year", "--output", str(output)])

    module.main()

    report = json.loads(output.read_text())
    assert report["cases"] == []
    assert report["preflight_api_error"] == "RuntimeError: metadata endpoint unavailable"
    assert report["unrun_cases"] == ["missing_year"]
    factory.assert_not_called()


@pytest.mark.parametrize("seconds", ["0", "-1", "nan", "inf"])
def test_invalid_wait_budget_is_rejected_before_network_access(probe, monkeypatch, seconds):
    module, factory, _ = probe
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--gradio-timeout-seconds", seconds])

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 2
    module.requests.get.assert_not_called()
    factory.assert_not_called()
