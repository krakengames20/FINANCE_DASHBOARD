"""A transient model failure must recover on rerun without displaying NaN."""

import pytest

import app
from src.ui import nowcast
from src.ui.views import dashboard


@pytest.fixture(autouse=True)
def clear_report_cache():
    app._load_probit_report.clear()
    yield
    app._load_probit_report.clear()


def test_failed_calculation_is_retried_then_success_is_cached(monkeypatch):
    calls = []

    def compute():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("temporary data outage")
        return {"ensemble_probability": 12.4}

    monkeypatch.setattr(app, "compute_probit_report", compute)
    with pytest.raises(RuntimeError, match="temporary data outage"):
        app._load_probit_report("test-recovery")
    assert app._load_probit_report("test-recovery")["ensemble_probability"] == 12.4
    assert app._load_probit_report("test-recovery")["ensemble_probability"] == 12.4
    assert len(calls) == 2


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), None])
def test_invalid_probability_is_not_cached(monkeypatch, probability):
    reports = iter([{"ensemble_probability": probability}, {"ensemble_probability": 12.4}])
    monkeypatch.setattr(app, "compute_probit_report", lambda: next(reports))
    with pytest.raises(RuntimeError, match="non-finite"):
        app._load_probit_report("test-invalid")
    assert app._load_probit_report("test-invalid")["ensemble_probability"] == 12.4


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), float("-inf"), None])
def test_missing_headline_is_a_dash(probability):
    assert nowcast.headline_value_text({"ensemble_probability": probability}) == "—"


def test_failed_report_displays_cause_without_recession_badge(monkeypatch):
    current, history = app._recession_view({"probit": {"error": "temporary data outage"}})
    markup, warnings = [], []
    monkeypatch.setattr(dashboard.st, "markdown", lambda html, **kwargs: markup.append(html))
    monkeypatch.setattr(dashboard.st, "warning", warnings.append)
    dashboard._recession_card(current, history)
    assert "UNAVAILABLE" in markup[0]
    assert "IN RECESSION" not in markup[0]
    assert "nan" not in markup[0].lower()
    assert "temporary data outage" in warnings[0]
