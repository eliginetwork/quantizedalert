"""Tests for OpenAI-compatible LLM configuration and explanation polish."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from quantizedalert.agents.research import ResearchExplanationAgent


def test_research_explanation_default_template(monkeypatch):
    """When no LLM model is configured, returns deterministic template prose."""
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("QUANTIZEDALERT_LLM_MODEL", raising=False)
    monkeypatch.delenv("UNLOCKAID_LLM_MODEL", raising=False)

    agent = ResearchExplanationAgent()
    bt = {
        "freq": "1d",
        "ann_return": 0.285,
        "information_ratio": 1.95,
        "max_drawdown": -0.072,
        "mean_turnover": 0.12,
    }
    ic = {"ic": 0.0185, "rank_ic": 0.0212, "n": 25000}
    val = {"passed": True, "overfit_flags": []}

    out = agent.explain_run("demo [ridge/Alpha158]", bt, ic, val)
    assert "[engine_source=template]" in out
    assert "0.018" in out
    assert "28.5%" in out
    assert "1.95" in out
    assert "Validation passed all robustness gates" in out


def test_research_explanation_openai_compatible_success(monkeypatch):
    """When OPENAI_MODEL and custom endpoint are set, uses OpenAI client."""
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Polished quant summary with exact numbers."

    agent = ResearchExplanationAgent()
    bt = {
        "freq": "1d",
        "ann_return": 0.30,
        "information_ratio": 2.0,
        "max_drawdown": -0.05,
        "mean_turnover": 0.10,
    }
    ic = {"ic": 0.02, "rank_ic": 0.025, "n": 10000}
    val = {"passed": True}

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        out = agent.explain_run("test_model", bt, ic, val)

        mock_openai_cls.assert_called_once_with(
            api_key="sk-test-key",
            base_url="https://api.deepseek.com/v1",
        )
        assert mock_client.chat.completions.create.call_count == 1
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "deepseek-chat"
        assert out == "Polished quant summary with exact numbers."


def test_research_explanation_quantizedalert_alias(monkeypatch):
    """QUANTIZEDALERT_LLM_MODEL is supported as alias for OPENAI_MODEL."""
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("QUANTIZEDALERT_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("QUANTIZEDALERT_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("QUANTIZEDALERT_LLM_API_KEY", "ollama")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Ollama polished explanation."

    agent = ResearchExplanationAgent()
    bt = {
        "freq": "1d",
        "ann_return": 0.15,
        "information_ratio": 1.2,
        "max_drawdown": -0.10,
        "mean_turnover": 0.15,
    }
    ic = {"ic": 0.01, "rank_ic": 0.015, "n": 5000}
    val = {"passed": False, "overfit_flags": ["high_turnover"]}

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        out = agent.explain_run("test_model", bt, ic, val)

        mock_openai_cls.assert_called_once_with(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        assert out == "Ollama polished explanation."


def test_research_explanation_legacy_alias(monkeypatch):
    """UNLOCKAID_LLM_MODEL is supported as alias for OPENAI_MODEL."""
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("QUANTIZEDALERT_LLM_MODEL", raising=False)
    monkeypatch.setenv("UNLOCKAID_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("UNLOCKAID_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("UNLOCKAID_LLM_API_KEY", "ollama")

    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = "Ollama polished explanation."

    agent = ResearchExplanationAgent()
    bt = {
        "freq": "1d",
        "ann_return": 0.15,
        "information_ratio": 1.2,
        "max_drawdown": -0.10,
        "mean_turnover": 0.15,
    }
    ic = {"ic": 0.01, "rank_ic": 0.015, "n": 5000}
    val = {"passed": False, "overfit_flags": ["high_turnover"]}

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        out = agent.explain_run("test_model", bt, ic, val)

        mock_openai_cls.assert_called_once_with(
            api_key="ollama",
            base_url="http://localhost:11434/v1",
        )
        assert out == "Ollama polished explanation."


def test_research_explanation_fallback_on_error(monkeypatch):
    """When the LLM endpoint fails, falls back cleanly to tagged template prose."""
    monkeypatch.setenv("OPENAI_MODEL", "broken-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://unreachable-host:9999/v1")

    agent = ResearchExplanationAgent()
    bt = {
        "freq": "1d",
        "ann_return": 0.20,
        "information_ratio": 1.5,
        "max_drawdown": -0.08,
        "mean_turnover": 0.10,
    }
    ic = {"ic": 0.015, "rank_ic": 0.02, "n": 12000}
    val = {"passed": True}

    with patch("openai.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = ConnectionError("Endpoint down")

        out = agent.explain_run("test_model", bt, ic, val)
        assert "[engine_source=template-fallback:ConnectionError]" in out
        assert "20.0%" in out
        assert "1.50" in out
