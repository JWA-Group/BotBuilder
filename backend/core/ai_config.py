"""Load AI assistant settings from Electron settings.json / env fallbacks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from backend.core.app_paths import get_app_root, get_data_dir

# OpenAI-compatible base URLs (…/v1) used by /chat/completions
PROVIDER_PRESETS = {
    "deepseek": {
        "endpoint": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "planner": "deepseek-chat",
        "coder": "deepseek-reasoner",
        "scenario": "deepseek-chat",
    },
    "openai": {
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "planner": "gpt-4o-mini",
        "coder": "gpt-4o",
        "scenario": "gpt-4o-mini",
    },
    "openrouter": {
        "endpoint": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "planner": "openai/gpt-4o-mini",
        "coder": "openai/gpt-4o",
        "scenario": "openai/gpt-4o-mini",
    },
    "custom": {
        "endpoint": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "planner": "gpt-4o",
        "coder": "gpt-4o",
        "scenario": "gpt-4o",
    },
}


@dataclass
class AIConfig:
    endpoint: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: str = ""
    enabled: bool = False
    provider: str = "custom"
    model_planner: str = "gpt-4o"
    model_coder: str = "gpt-4o"
    model_scenario: str = "gpt-4o"
    # Writes the parts of a split task; empty falls back to the planner model.
    model_worker: str = ""

    def model_for_role(self, role: str) -> str:
        """Return model id for planner | coder | scenario | worker (fallback → model)."""
        role = (role or "").strip().lower()
        mapping = {
            "planner": self.model_planner,
            "chat": self.model_planner,
            "coder": self.model_coder,
            "plugin": self.model_coder,
            "scenario": self.model_scenario,
            "worker": self.model_worker or self.model_planner,
        }
        picked = (mapping.get(role) or self.model or "").strip()
        return picked or self.model or "gpt-4o"


def settings_json_path() -> Path:
    """
    Electron stores settings at userData/settings.json.
    BOTBUILDER_DATA_DIR points at userData/data → parent is userData.
    """
    data_dir = get_data_dir()
    candidate = data_dir.parent / "settings.json"
    if candidate.is_file():
        return candidate
    legacy = get_app_root() / "settings.json"
    return legacy


def normalize_chat_completions_base(endpoint: str) -> str:
    """
    Normalize provider base so `{base}/chat/completions` is correct.
    Accepts https://api.deepseek.com or …/v1 (with or without trailing slash).
    """
    raw = (endpoint or "").strip().rstrip("/")
    if not raw:
        return "https://api.openai.com/v1"
    lower = raw.lower()
    # Already points at chat/completions
    if lower.endswith("/chat/completions"):
        return raw[: -len("/chat/completions")].rstrip("/")
    # DeepSeek root without /v1
    if "api.deepseek.com" in lower and not lower.rstrip("/").endswith("/v1"):
        # https://api.deepseek.com → …/v1
        if lower.rstrip("/").endswith("api.deepseek.com"):
            return raw + "/v1"
    return raw


def _pick_str(*candidates: object, default: str = "") -> str:
    for c in candidates:
        if isinstance(c, str) and c.strip():
            return c.strip()
    return default


def load_ai_config() -> AIConfig:
    endpoint = "https://api.openai.com/v1"
    model = "gpt-4o"
    api_key = ""
    enabled = False
    provider = "custom"
    model_planner = ""
    model_coder = ""
    model_scenario = ""
    model_worker = ""

    path = settings_json_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if isinstance(raw.get("aiEndpoint"), str) and raw["aiEndpoint"].strip():
                    endpoint = raw["aiEndpoint"].strip().rstrip("/")
                if isinstance(raw.get("aiModel"), str) and raw["aiModel"].strip():
                    model = raw["aiModel"].strip()
                if isinstance(raw.get("aiKey"), str):
                    api_key = raw["aiKey"].strip()
                enabled = bool(raw.get("aiEnabled"))
                if isinstance(raw.get("aiProvider"), str) and raw["aiProvider"].strip():
                    provider = raw["aiProvider"].strip().lower()
                model_planner = _pick_str(raw.get("aiModelPlanner"))
                model_coder = _pick_str(raw.get("aiModelCoder"))
                model_scenario = _pick_str(raw.get("aiModelScenario"))
                model_worker = _pick_str(raw.get("aiModelWorker"))
        except (OSError, ValueError, TypeError):
            pass

    if not api_key:
        api_key = (
            os.environ.get("BOTBUILDER_AI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("AI_API_KEY")
            or ""
        ).strip()
    env_endpoint = (os.environ.get("BOTBUILDER_AI_ENDPOINT") or "").strip().rstrip("/")
    if env_endpoint:
        endpoint = env_endpoint
    env_model = (os.environ.get("BOTBUILDER_AI_MODEL") or "").strip()
    if env_model:
        model = env_model
    if os.environ.get("BOTBUILDER_AI_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        enabled = True
    env_provider = (os.environ.get("BOTBUILDER_AI_PROVIDER") or "").strip().lower()
    if env_provider:
        provider = env_provider

    if provider not in PROVIDER_PRESETS:
        # Infer from endpoint
        low = endpoint.lower()
        if "deepseek" in low:
            provider = "deepseek"
        elif "openrouter" in low:
            provider = "openrouter"
        elif "openai.com" in low:
            provider = "openai"
        else:
            provider = "custom"

    endpoint = normalize_chat_completions_base(endpoint)
    fallback = model or PROVIDER_PRESETS.get(provider, {}).get("model") or "gpt-4o"
    model_planner = model_planner or fallback
    model_coder = model_coder or fallback
    model_scenario = model_scenario or fallback

    return AIConfig(
        endpoint=endpoint,
        model=fallback,
        api_key=api_key,
        enabled=enabled,
        provider=provider,
        model_planner=model_planner,
        model_coder=model_coder,
        model_scenario=model_scenario,
        model_worker=model_worker or (os.environ.get("BOTBUILDER_AI_MODEL_WORKER") or "").strip(),
    )


def require_ai_ready() -> AIConfig:
    """Raise ValueError if AI is disabled or misconfigured."""
    cfg = load_ai_config()
    if not cfg.enabled:
        raise ValueError("AI assistant is disabled. Enable it in Application settings.")
    if not cfg.api_key:
        raise ValueError("AI API key is not configured. Add it in Application settings.")
    if not cfg.endpoint:
        raise ValueError("AI API endpoint is empty.")
    return cfg
