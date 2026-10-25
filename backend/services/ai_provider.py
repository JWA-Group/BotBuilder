"""OpenAI-compatible chat completions client for BotBuilder AI assistant."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Callable, Type, TypeVar

import aiohttp
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from backend.core.ai_config import AIConfig, normalize_chat_completions_base
from backend.services.ai_progress import AgentCancelled

log = logging.getLogger("ai_provider")

# No artificial output cap: request a high ceiling and learn the model's real cap
# from the provider's error message. max_tokens is only a ceiling, short answers
# cost the same regardless of it.
UNLIMITED_MAX_TOKENS = 65536
SAFE_FALLBACK_MAX_TOKENS = 8192
# Each piece of a split task gets a small budget so it stays focused and cheap.
SUBTASK_MAX_TOKENS = 12000
# Loop guards replace a hard step cap: stop on no-progress, not on step count.
MAX_REPEATED_CALLS = 3
MAX_CONSECUTIVE_FAILURES = 5

_MODEL_OUTPUT_CAP: dict[str, int] = {}

_CAP_PATTERNS = (
    re.compile(r"\[\s*1\s*,\s*(\d{3,7})\s*\]"),
    re.compile(r"at most\s+(\d{3,7})", re.I),
    re.compile(r"(?:<=|less than or equal to|maximum(?: value)?(?: is| of)?)\s*(\d{3,7})", re.I),
)
_CTX_PATTERN = re.compile(r"context length is\s*(\d+)", re.I)
_PROMPT_TOKENS_PATTERN = re.compile(r"(\d+)\s*(?:tokens\s*)?in the messages", re.I)


def _timeout_for(max_tokens: int) -> int:
    """Long generations at a high ceiling legitimately take minutes."""
    return int(min(900, max(180, max_tokens / 60)))


def model_output_cap(model: str) -> int | None:
    return _MODEL_OUTPUT_CAP.get(model)


def _effective_max_tokens(model: str, requested: int) -> int:
    cap = _MODEL_OUTPUT_CAP.get(model)
    return min(requested, cap) if cap else requested


def _cap_from_limit_error(detail: str, requested: int) -> int | None:
    """Parse the provider's real output cap from a rejected request; None if unrelated error."""
    low = (detail or "").lower()
    if not any(k in low for k in ("max_tokens", "max tokens", "completion tokens", "context length",
                                   "output tokens", "max_completion_tokens")):
        return None
    ctx = _CTX_PATTERN.search(detail)
    if ctx:
        prompt = _PROMPT_TOKENS_PATTERN.search(detail)
        used = int(prompt.group(1)) if prompt else 0
        value = int(ctx.group(1)) - used - 256
        return max(1024, min(value, requested - 1))
    for pat in _CAP_PATTERNS:
        m = pat.search(detail)
        if m and int(m.group(1)) < requested:
            return int(m.group(1))
    if requested > SAFE_FALLBACK_MAX_TOKENS:
        return SAFE_FALLBACK_MAX_TOKENS
    return None


def _remember_cap(model: str, cap: int) -> None:
    prev = _MODEL_OUTPUT_CAP.get(model)
    if prev is None or cap < prev:
        _MODEL_OUTPUT_CAP[model] = cap
        log.info("learned output token cap for %s: %s", model, cap)


TRUNCATION_NUDGE = (
    "SYSTEM NOTICE: your previous response was cut off by the output token limit, so no "
    "tool call was executed and NOTHING changed. Do not reason at length. Respond with the "
    "tool call(s) right away. Keep script_code compact: no long comments or docstrings."
)
SPLIT_NUDGE = (
    "SYSTEM NOTICE: this task does not fit into one response even at the model's maximum "
    "output size. Call plan_task NOW to split it into small subtasks (one file or one "
    "scenario change each). Do not write any code in this response."
)
CANCELLED_REPLY = "Остановлено пользователем. Уже выполненные шаги сохранены."
SUBTASK_SPLIT_REPLY = (
    "SUBTASK_TOO_LARGE: this subtask does not fit into one response. Split it into smaller "
    "subtasks with plan_task (for example one file per subtask or a file in several modules)."
)

NO_ACTION_REPLY = (
    "Изменения не применены: модель не вызвала ни одного инструмента, файлы и сценарий "
    "остались прежними. Повторите запрос."
)
TRUNCATED_REPLY = (
    "Изменения не применены: ответ модели обрезан лимитом токенов "
    "(finish_reason=length) {n} раз подряд. Попробуйте разбить задачу на шаги, "
    "например сначала только изменить скрипт, затем отдельно сценарий."
)

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token)\s*[:=]\s*[\"']?[^\s\"']+",
)
# DeepSeek-R1 / reasoner chain-of-thought wrappers
_THINK_TAG_RE = re.compile(
    r"<(?:thought|think|reasoning|redacted_reasoning)\b[^>]*>[\s\S]*?</(?:thought|think|reasoning|redacted_reasoning)>",
    re.IGNORECASE,
)
_THINK_UNCLOSED_RE = re.compile(
    r"<(?:thought|think|reasoning)\b[^>]*>[\s\S]*$",
    re.IGNORECASE,
)

T = TypeVar("T", bound=BaseModel)


def _truncate(s: str, n: int = 4000) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def sanitize_secrets(text: str) -> str:
    """Strip API keys / Bearer tokens from anything that may hit monitor logs."""
    if not text:
        return ""
    out = _SECRET_RE.sub(r"\1: [REDACTED]", text)
    out = re.sub(r"\bsk-[A-Za-z0-9_\-]{8,}\b", "[REDACTED_KEY]", out)
    out = re.sub(r"\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b", "Bearer [REDACTED]", out, flags=re.I)
    return out


def strip_reasoning_tags(text: str) -> str:
    """Remove DeepSeek-R1 / reasoner <think>/<thought> blocks before JSON parse."""
    if not text:
        return ""
    out = _THINK_TAG_RE.sub("", text)
    out = _THINK_UNCLOSED_RE.sub("", out)
    return out.strip()


def _content_from_message(msg: Any) -> str:
    """Normalize OpenAI / DeepSeek message.content (str or multimodal list)."""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, list):
        parts: list[str] = []
        for p in msg:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                if isinstance(p.get("text"), str):
                    parts.append(p["text"])
                elif isinstance(p.get("content"), str):
                    parts.append(p["content"])
        return "\n".join(parts)
    return str(msg or "")


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse JSON object from model output (reasoning strip, fences, trailing commas)."""
    raw = strip_reasoning_tags(text or "")
    if not raw:
        raise ValueError("Пустой ответ модели (ожидался JSON)")

    if "```" in raw:
        fence = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)```", raw)
        if fence:
            raw = fence.group(1).strip()
        else:
            lines = raw.split("\n")
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

    candidates = [raw]
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])

    last_err: Exception | None = None
    for cand in candidates:
        for variant in (cand, _TRAILING_COMMA_RE.sub(r"\1", cand)):
            try:
                data = json.loads(variant)
            except json.JSONDecodeError as exc:
                last_err = exc
                continue
            if isinstance(data, dict):
                return data
            last_err = ValueError("Корень JSON должен быть объектом {}")
    preview = _truncate(raw.replace("\n", " "), 180)
    raise ValueError(
        f"Модель вернула невалидный JSON: {last_err}. Фрагмент: {preview}"
    ) from last_err


class AIProvider:
    def __init__(self, config: AIConfig) -> None:
        self.config = config

    async def complete(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        purpose: str = "chat",
        bot_id: str | int | None = None,
        model: str | None = None,
    ) -> str:
        """
        Call chat completions. If json_mode fails on provider (unsupported),
        retries once without response_format.
        """
        resolved_model = (model or self.config.model or "").strip() or self.config.model
        try:
            return await self._complete_once(
                messages,
                system_prompt,
                json_mode=json_mode,
                temperature=temperature,
                purpose=purpose,
                bot_id=bot_id,
                model=resolved_model,
            )
        except HTTPException as exc:
            detail = str(exc.detail or "").lower()
            if json_mode and (
                "response_format" in detail
                or "json_object" in detail
                or "not support" in detail
                or "unsupported" in detail
            ):
                log.warning("json_mode unsupported, retrying without: %s", exc.detail)
                return await self._complete_once(
                    messages,
                    system_prompt,
                    json_mode=False,
                    temperature=temperature,
                    purpose=purpose + " (no-json-mode)",
                    bot_id=bot_id,
                    model=resolved_model,
                )
            raise

    async def call_structured_llm(
        self,
        messages: list[dict[str, str]],
        response_model: Type[T],
        *,
        system_prompt: str = "",
        max_retries: int = 2,
        temperature: float = 0.1,
        purpose: str = "structured",
        bot_id: str | int | None = None,
        json_mode: bool = True,
        model: str | None = None,
    ) -> T:
        """
        Self-correction loop (docs/AI_ASSISTANT.md §4):
        validate LLM JSON with Pydantic; on ValidationError feed trace back (up to max_retries).
        """
        current = [dict(m) for m in messages]
        last_err: Exception | None = None
        use_json_mode = json_mode
        resolved_model = (model or self.config.model or "").strip() or self.config.model

        for attempt in range(max_retries + 1):
            raw_response = await self.complete(
                current,
                system_prompt,
                json_mode=use_json_mode,
                temperature=temperature,
                purpose=f"{purpose}#try{attempt}",
                bot_id=bot_id,
                model=resolved_model,
            )
            # Strip reasoner CoT before validation
            cleaned = strip_reasoning_tags(raw_response)
            try:
                try:
                    obj = extract_json_object(cleaned)
                    payload = json.dumps(obj, ensure_ascii=False)
                except ValueError:
                    payload = cleaned
                validated = response_model.model_validate_json(payload)
                return validated
            except (ValidationError, ValueError, json.JSONDecodeError) as err:
                last_err = err
                self._emit_validation_fail(
                    purpose=purpose,
                    attempt=attempt,
                    error=str(err),
                    raw_response=raw_response,
                    bot_id=bot_id,
                )
                if attempt >= max_retries:
                    break
                if attempt >= 1:
                    use_json_mode = False
                correction = (
                    f"Your previous response failed validation with error:\n{err}\n"
                    f"Please fix all schema violations and return ONLY valid JSON "
                    f"matching the required schema. No markdown fences, no <think> tags."
                )
                current.append({"role": "assistant", "content": cleaned[:12000] or raw_response[:12000]})
                current.append({"role": "user", "content": correction})

        raise HTTPException(
            status_code=502,
            detail=f"LLM schema validation failed after retries: {last_err}",
        ) from last_err

    async def _complete_once(
        self,
        messages: list[dict[str, str]],
        system_prompt: str,
        *,
        json_mode: bool,
        temperature: float,
        purpose: str,
        bot_id: str | int | None,
        model: str,
        max_tokens: int = UNLIMITED_MAX_TOKENS,
    ) -> str:
        base = normalize_chat_completions_base(self.config.endpoint)
        url = f"{base}/chat/completions"
        max_tokens = _effective_max_tokens(model, max_tokens)
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        # deepseek-reasoner often ignores/rejects json_object — still try; fallback above
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        user_preview = ""
        if messages:
            user_preview = _truncate(str(messages[-1].get("content") or ""), 2400)
        sys_preview = _truncate(system_prompt, 2000)

        t0 = time.perf_counter()
        status = 0
        text = ""
        try:
            timeout = aiohttp.ClientTimeout(total=_timeout_for(max_tokens))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    text = await resp.text()
                    status = resp.status
        except aiohttp.ClientError as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=0,
                ms=ms,
                bot_id=bot_id,
                error=str(exc),
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview="",
            )
            log.warning("AI provider transport error: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"AI-провайдер недоступен: {exc}",
            ) from exc

        ms = int((time.perf_counter() - t0) * 1000)

        try:
            data = json.loads(text) if text else {}
        except ValueError as exc:
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error=f"HTTP body is not JSON: {_truncate(text, 200)}",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
            )
            raise HTTPException(
                status_code=502,
                detail=f"AI-провайдер вернул не-JSON ({status}): {_truncate(text, 200)}",
            ) from exc

        if status >= 400:
            detail = ""
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err)
                elif err:
                    detail = str(err)
                else:
                    detail = str(data.get("message") or data)[:400]
            cap = _cap_from_limit_error(detail, max_tokens)
            if cap:
                _remember_cap(model, cap)
                return await self._complete_once(
                    messages,
                    system_prompt,
                    json_mode=json_mode,
                    temperature=temperature,
                    purpose=purpose,
                    bot_id=bot_id,
                    model=model,
                    max_tokens=cap,
                )
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error=detail or f"HTTP {status}",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
            )
            raise HTTPException(
                status_code=502,
                detail=detail or f"AI provider HTTP {status}",
            )

        try:
            msg = data["choices"][0]["message"]
            content = _content_from_message(msg.get("content") if isinstance(msg, dict) else msg)
        except (KeyError, IndexError, TypeError) as exc:
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error="missing choices[0].message.content",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
            )
            raise HTTPException(
                status_code=502,
                detail="Ответ AI без choices[0].message.content",
            ) from exc

        if not isinstance(content, str) or not content.strip():
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error="empty content",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
            )
            raise HTTPException(status_code=502, detail="AI вернул пустой ответ")

        usage = data.get("usage") if isinstance(data, dict) else None
        tokens = ""
        if isinstance(usage, dict):
            tokens = (
                f" tokens in={usage.get('prompt_tokens')} "
                f"out={usage.get('completion_tokens')}"
            )

        self._emit_monitor(
            purpose=purpose,
            ok=True,
            status=status,
            ms=ms,
            bot_id=bot_id,
            error="",
            request_preview=user_preview,
            system_preview=sys_preview,
            response_preview=_truncate(content, 8000),
            extra=tokens.strip(),
            model=model,
        )
        # Strip CoT tags for callers (JSON parse / chat display)
        return strip_reasoning_tags(content.strip()) or content.strip()

    async def complete_raw(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
        temperature: float = 0.2,
        purpose: str = "chat-tools",
        bot_id: str | int | None = None,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int = UNLIMITED_MAX_TOKENS,
    ) -> dict[str, Any]:
        """
        Low-level chat completion returning the assistant message dict
        (content + optional tool_calls). OpenAI / DeepSeek / Anthropic-proxy compatible.
        `_finish_reason` is attached so callers can detect output truncation.
        """
        resolved_model = (model or self.config.model or "").strip() or self.config.model
        max_tokens = _effective_max_tokens(resolved_model, max_tokens)
        base = normalize_chat_completions_base(self.config.endpoint)
        url = f"{base}/chat/completions"
        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]
        payload: dict[str, Any] = {
            "model": resolved_model,
            "temperature": temperature,
            "max_tokens": int(max_tokens),
            "messages": api_messages,
        }
        if tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if json_mode and not tools:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        user_preview = ""
        for m in reversed(messages):
            if isinstance(m, dict) and m.get("role") == "user":
                user_preview = _truncate(str(m.get("content") or ""), 2400)
                break
        sys_preview = _truncate(system_prompt, 2000)
        tools_preview = f"tools={len(tools)}" if tools else ""

        t0 = time.perf_counter()
        status = 0
        text = ""
        try:
            timeout = aiohttp.ClientTimeout(total=_timeout_for(max_tokens))
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    text = await resp.text()
                    status = resp.status
        except aiohttp.ClientError as exc:
            ms = int((time.perf_counter() - t0) * 1000)
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=0,
                ms=ms,
                bot_id=bot_id,
                error=str(exc),
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview="",
                extra=tools_preview,
                model=resolved_model,
            )
            raise HTTPException(
                status_code=502,
                detail=f"AI-провайдер недоступен: {exc}",
            ) from exc

        ms = int((time.perf_counter() - t0) * 1000)
        try:
            data = json.loads(text) if text else {}
        except ValueError as exc:
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error=f"HTTP body is not JSON: {_truncate(text, 200)}",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
                model=resolved_model,
            )
            raise HTTPException(
                status_code=502,
                detail=f"AI-провайдер вернул не-JSON ({status}): {_truncate(text, 200)}",
            ) from exc

        if status >= 400:
            detail = ""
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err)
                elif err:
                    detail = str(err)
                else:
                    detail = str(data.get("message") or data)[:400]
            # Provider caps output tokens lower than requested: learn the cap, retry.
            cap = _cap_from_limit_error(detail, max_tokens)
            if cap:
                log.warning("provider rejected max_tokens=%s, retrying with %s: %s",
                            max_tokens, cap, detail)
                _remember_cap(resolved_model, cap)
                return await self.complete_raw(
                    messages,
                    system_prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    purpose=purpose,
                    bot_id=bot_id,
                    model=model,
                    json_mode=json_mode,
                    max_tokens=cap,
                )
            # Retry once without tools if provider rejects tools schema
            if tools and (
                "tool" in detail.lower()
                or "function" in detail.lower()
                or "not support" in detail.lower()
            ):
                log.warning("tools unsupported, falling back to text: %s", detail)
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": None,
                    "_tools_unsupported": True,
                    "_error": detail,
                }
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error=detail or f"HTTP {status}",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
                model=resolved_model,
            )
            raise HTTPException(
                status_code=502,
                detail=detail or f"AI provider HTTP {status}",
            )

        try:
            msg = data["choices"][0]["message"]
            if not isinstance(msg, dict):
                raise TypeError("message is not dict")
        except (KeyError, IndexError, TypeError) as exc:
            self._emit_monitor(
                purpose=purpose,
                ok=False,
                status=status,
                ms=ms,
                bot_id=bot_id,
                error="missing choices[0].message",
                request_preview=user_preview,
                system_preview=sys_preview,
                response_preview=_truncate(text, 6000),
                model=resolved_model,
            )
            raise HTTPException(
                status_code=502,
                detail="Ответ AI без choices[0].message",
            ) from exc

        content = _content_from_message(msg.get("content"))
        content = strip_reasoning_tags(content) if content else ""
        tool_calls = msg.get("tool_calls")
        if tool_calls is not None and not isinstance(tool_calls, list):
            tool_calls = None

        usage = data.get("usage") if isinstance(data, dict) else None
        tokens = ""
        if isinstance(usage, dict):
            tokens = (
                f" tokens in={usage.get('prompt_tokens')} "
                f"out={usage.get('completion_tokens')}"
            )
        tc_n = len(tool_calls) if tool_calls else 0
        try:
            finish_reason = str(data["choices"][0].get("finish_reason") or "")
        except (KeyError, IndexError, TypeError, AttributeError):
            finish_reason = ""
        truncated = finish_reason == "length"
        self._emit_monitor(
            purpose=purpose,
            ok=not truncated,
            status=status,
            ms=ms,
            bot_id=bot_id,
            error=(
                f"output truncated at max_tokens={max_tokens} (finish_reason=length)"
                if truncated
                else ""
            ),
            request_preview=user_preview,
            system_preview=sys_preview,
            response_preview=_truncate(
                content or (f"[tool_calls:{tc_n}]" if tc_n else ""),
                8000,
            ),
            extra=(
                tokens
                + (f" tool_calls={tc_n}" if tc_n else "")
                + (f" {tools_preview}" if tools_preview else "")
                + (f" finish={finish_reason}" if finish_reason else "")
            ).strip(),
            model=resolved_model,
        )
        return {
            "role": "assistant",
            "content": content or "",
            "tool_calls": tool_calls,
            "_finish_reason": finish_reason,
        }

    async def run_tool_loop(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        executor: Any,
        *,
        max_rounds: int | None = None,
        temperature: float = 0.2,
        purpose: str = "agent",
        bot_id: str | int | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        split_tool: str | None = None,
        on_event: Callable[[str, str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Native tool-calling agent loop.
        `executor(name: str, args: dict) -> dict | str` (sync or async).
        Returns (final_assistant_text, executed_tool_records).

        One `round` = one LLM completion. ALL tool_calls from that completion
        are executed in the same round (batch) before the next LLM call.

        Truncated responses (finish_reason=length) are never executed. The loop
        first retries with the model's maximum output; if the task still does not
        fit and `split_tool` is available, the model is forced to split the task.
        Without `split_tool` (inside a subtask) it reports SUBTASK_SPLIT_REPLY so
        the parent can split further.
        """
        import inspect

        try:
            from backend.services.ai_intent import MAX_AGENT_STEPS
        except Exception:
            MAX_AGENT_STEPS = 200
        if max_rounds is None:
            max_rounds = MAX_AGENT_STEPS

        resolved_model = (model or self.config.model or "").strip() or self.config.model
        tool_names = {
            str((t.get("function") or {}).get("name") or "") for t in tools if isinstance(t, dict)
        }
        can_split = bool(split_tool and split_tool in tool_names)

        working = [dict(m) for m in messages]
        executed: list[dict[str, Any]] = []
        final_text = ""
        max_tokens = int(max_tokens or UNLIMITED_MAX_TOKENS)
        tool_choice: Any = "auto"
        split_forced = False
        call_counts: dict[str, int] = {}
        consecutive_failures = 0

        def emit(kind: str, text: str) -> None:
            if on_event is not None:
                try:
                    on_event(kind, text)
                except Exception:
                    log.debug("progress emit failed", exc_info=True)

        async def await_llm(coro: Any) -> dict[str, Any]:
            # Poll the stop flag while the model generates, so Stop works mid-response.
            task = asyncio.ensure_future(coro)
            if should_stop is None:
                return await task
            while True:
                done, _ = await asyncio.wait({task}, timeout=0.5)
                if done:
                    return task.result()
                if should_stop():
                    task.cancel()
                    raise AgentCancelled()

        for round_i in range(max_rounds):
            if should_stop is not None and should_stop():
                return CANCELLED_REPLY, executed
            emit("think", f"Модель думает (шаг {round_i + 1})")
            try:
                msg = await await_llm(
                    self.complete_raw(
                        working,
                        system_prompt,
                        tools=tools,
                        tool_choice=tool_choice,
                        temperature=temperature,
                        purpose=f"{purpose}#r{round_i}",
                        bot_id=bot_id,
                        model=model,
                        max_tokens=max_tokens,
                    )
                )
            except AgentCancelled:
                return CANCELLED_REPLY, executed
            tool_choice = "auto"
            if msg.get("_finish_reason") == "length":
                # Tool-call JSON of a truncated response is incomplete: never execute it.
                ceiling = model_output_cap(resolved_model) or UNLIMITED_MAX_TOKENS
                log.warning(
                    "[LLM Raw Response] truncated at max_tokens=%s (model ceiling %s)",
                    max_tokens, ceiling,
                )
                if max_tokens < ceiling:
                    max_tokens = ceiling
                    emit("warn", "Ответ не поместился, повторяю с максимальным лимитом")
                    if not any(m.get("content") == TRUNCATION_NUDGE for m in working):
                        working.append({"role": "user", "content": TRUNCATION_NUDGE})
                    continue
                if can_split and not split_forced:
                    split_forced = True
                    emit("warn", "Задача слишком большая для одного ответа, разбиваю на части")
                    working.append({"role": "user", "content": SPLIT_NUDGE})
                    tool_choice = {"type": "function", "function": {"name": split_tool}}
                    continue
                if not split_tool:
                    return SUBTASK_SPLIT_REPLY, executed
                return TRUNCATED_REPLY.format(n=2), executed
            if msg.get("_tools_unsupported"):
                # Fallback: plain completion without tools
                text = await self.complete(
                    [{"role": m["role"], "content": str(m.get("content") or "")} for m in working if m.get("role") in ("user", "assistant")],
                    system_prompt,
                    json_mode=False,
                    temperature=temperature,
                    purpose=purpose + "-no-tools",
                    bot_id=bot_id,
                    model=model,
                )
                return strip_reasoning_tags(text) or text, executed

            tool_calls = msg.get("tool_calls") or []
            content = str(msg.get("content") or "")
            if content:
                final_text = content

            if tool_calls:
                names = []
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                        names.append(str(fn.get("name") or tc.get("name") or "?"))
                print(
                    f"[INFO] LOG: [LLM Raw Response] -> Tool calls detected: {names} "
                    f"(batch in round {round_i + 1}/{max_rounds})"
                )
                log.info(
                    "[LLM Raw Response] Tool calls detected: %s (round %s/%s)",
                    names,
                    round_i + 1,
                    max_rounds,
                )
            else:
                print("[INFO] LOG: [LLM Raw Response] -> No tool_calls (text-only reply)")
                log.info("[LLM Raw Response] No tool_calls (text-only reply)")

            if not tool_calls:
                return final_text or (NO_ACTION_REPLY if not executed else ""), executed

            # Append assistant turn with tool_calls for the next round
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
            working.append(assistant_msg)

            # Batch: execute ALL tool_calls from this turn before next LLM round
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = str(fn.get("name") or "").strip()
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {"value": args}

                if should_stop is not None and should_stop():
                    return CANCELLED_REPLY, executed
                signature = name + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)[:4000]
                call_counts[signature] = call_counts.get(signature, 0) + 1
                if call_counts[signature] > MAX_REPEATED_CALLS:
                    return (
                        f"Агент остановлен: действие {name} повторяется с теми же данными "
                        f"{call_counts[signature]} раз без результата.",
                        executed,
                    )

                try:
                    result = executor(name, args)
                    if inspect.isawaitable(result):
                        result = await result
                except Exception as exc:
                    log.exception("tool %s raised", name)
                    result = {"ok": False, "error": str(exc)}

                if not isinstance(result, (dict, list, str, int, float, bool)) and result is not None:
                    result = {"ok": True, "result": str(result)}
                result_payload = result if isinstance(result, (dict, list)) else {"result": result}
                failed = isinstance(result_payload, dict) and result_payload.get("ok") is False
                consecutive_failures = consecutive_failures + 1 if failed else 0
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    executed.append(
                        {"id": tc.get("id"), "name": name, "arguments": args, "result": result_payload}
                    )
                    return (
                        f"Агент остановлен: {consecutive_failures} неудачных действий подряд. "
                        f"Последняя ошибка: {result_payload.get('error')}",
                        executed,
                    )
                executed.append(
                    {
                        "id": tc.get("id"),
                        "name": name,
                        "arguments": args,
                        "result": result_payload,
                    }
                )
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "content": json.dumps(result_payload, ensure_ascii=False)[:12000],
                    }
                )

        return final_text or "Достигнут лимит шагов агента.", executed

    def _emit_validation_fail(
        self,
        *,
        purpose: str,
        attempt: int,
        error: str,
        raw_response: str,
        bot_id: str | int | None,
    ) -> None:
        try:
            from backend.core.monitor import emit_llm

            msg = f"FAIL {purpose} · validation · try={attempt}"
            detail = (
                f"purpose: {purpose}\n"
                f"attempt: {attempt}\n"
                f"validation_error:\n{sanitize_secrets(error)}\n\n"
                f"--- raw response (trim) ---\n{_truncate(sanitize_secrets(raw_response), 6000)}"
            )
            emit_llm(msg, bot_id=bot_id, detail=detail)
        except Exception:
            log.debug("monitor validation emit failed", exc_info=True)

    def _emit_monitor(
        self,
        *,
        purpose: str,
        ok: bool,
        status: int,
        ms: int,
        bot_id: str | int | None,
        error: str,
        request_preview: str,
        system_preview: str,
        response_preview: str,
        extra: str = "",
        model: str = "",
    ) -> None:
        try:
            from backend.core.monitor import emit_llm

            model_name = model or self.config.model
            # Never log full endpoint with embedded credentials; strip query secrets
            endpoint = sanitize_secrets(self.config.endpoint.split("?")[0])
            flag = "OK" if ok else "FAIL"
            msg = (
                f"{flag} {purpose} · {model_name} · HTTP {status} · {ms}ms"
                + (f" · {extra}" if extra else "")
                + (f" · {sanitize_secrets(error)}" if error and not ok else "")
            )
            detail_parts = [
                f"endpoint: {endpoint}",
                f"model: {model_name}",
                f"purpose: {purpose}",
                f"status: {status}",
                f"latency_ms: {ms}",
            ]
            if error:
                detail_parts.append(f"error: {sanitize_secrets(error)}")
            if system_preview:
                detail_parts.append(
                    "--- system (trim) ---\n" + sanitize_secrets(system_preview)
                )
            if request_preview:
                detail_parts.append(
                    "--- user (trim) ---\n" + sanitize_secrets(request_preview)
                )
            if response_preview:
                detail_parts.append(
                    "--- response (trim) ---\n" + sanitize_secrets(response_preview)
                )
            emit_llm(msg, bot_id=bot_id, detail="\n\n".join(detail_parts))
        except Exception:
            log.debug("monitor emit_llm failed", exc_info=True)
