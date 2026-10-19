"""Request-local numeric token telemetry; no API calls, logs or prompt storage."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from math import ceil

_CURRENT_USAGE = ContextVar("agent_token_usage", default=None)
_LABELS = {"stage_2": "Stage 2 — Semantic classifier", "stage_3": "Stage 3 — Fallback classifier",
           "main_agent": "Main agent"}


def estimate_tokens(value):
    """Rough UTF-8 bytes / 4 estimate, not a model tokenizer or billing count."""
    if value is None or value == "":
        return 0
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return ceil(len(value.encode("utf-8")) / 4)


def _field(value, name):
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _input_estimates(parameters):
    schema = parameters.get("text_format")
    parts = {"instructions": estimate_tokens(parameters.get("instructions")),
             "tool_schemas": estimate_tokens(parameters.get("tools")),
             "response_schema": estimate_tokens(schema.model_json_schema()) if schema is not None else 0}
    messages = parameters.get("input", [])
    try:
        payload = json.loads(messages[-1]["content"])
    except (IndexError, KeyError, TypeError, ValueError):
        parts["messages"] = estimate_tokens(messages)
        return parts
    if not isinstance(payload, dict):
        parts["messages"] = estimate_tokens(messages)
        return parts
    parts["recent_conversation"] = estimate_tokens(messages[:-1]) if messages[:-1] else 0
    if "recent_conversation" in payload:
        parts["recent_conversation"] += estimate_tokens(payload["recent_conversation"])
    parts["user_request"] = estimate_tokens(payload.get("request", payload.get("current_message")))
    observations = payload.get("observations", {})
    for source in ("activities", "exams", "files", "memory"):
        parts[source] = estimate_tokens(observations.get(source))
    other = {key: value for key, value in payload.items()
             if key not in {"request", "current_message", "observations", "recent_conversation"}}
    parts["other_context"] = estimate_tokens(other) if other else 0
    return parts


def _visible_output(response):
    if response is None:
        return None
    parsed = _field(response, "output_parsed")
    if hasattr(parsed, "model_dump"):
        parsed = parsed.model_dump()
    visible = []
    if isinstance(parsed, (dict, list, str)):
        visible.append(parsed)
    output = _field(response, "output")
    if isinstance(output, list):
        for item in output:
            if _field(item, "type") == "function_call":
                visible.append({"tool": _field(item, "name"), "arguments": _field(item, "arguments")})
            elif parsed is None and _field(item, "type") == "message":
                for content in _field(item, "content") or []:
                    if _field(content, "type") == "output_text":
                        visible.append(_field(content, "text"))
    return estimate_tokens(visible) if visible else None


class TokenUsage:
    def __init__(self):
        self.calls = []

    def record(self, stage, parameters, response):
        parts = _input_estimates(parameters)
        usage = _field(response, "usage")
        input_count = _count(_field(usage, "input_tokens"))
        output_count = _count(_field(usage, "output_tokens"))
        reported = input_count is not None and output_count is not None
        if not reported:
            input_count, output_count = sum(parts.values()), _visible_output(response)
        cached = _count(_field(_field(usage, "input_tokens_details"), "cached_tokens")) if reported else None
        reasoning = _count(_field(_field(usage, "output_tokens_details"), "reasoning_tokens")) if reported else None
        if cached is not None and cached > input_count:
            cached = None
        if reasoning is not None and reasoning > output_count:
            reasoning = None
        ordinal = 1 + sum(item["stage"] == stage for item in self.calls)
        label = _LABELS[stage]
        if stage == "main_agent" and ordinal > 1:
            label += " — Recovery"
        elif ordinal > 1:
            label += f" — Call {ordinal}"
        status = _field(response, "status")
        self.calls.append({
            "stage": stage, "call": ordinal, "label": label,
            "model": parameters["model"],
            "status": status if status in {"completed", "incomplete", "failed"} else "usage_unavailable",
            "measurement": "reported" if reported else "estimated",
            "input_tokens": input_count, "output_tokens": output_count,
            "total_tokens": input_count + output_count if output_count is not None else None,
            "cached_input_tokens": cached, "reasoning_output_tokens": reasoning,
            "context_estimates": parts,
        })

    def snapshot(self):
        stages = [{"stage": "stage_1", "call": 0, "label": "Stage 1 — Local keyword router",
                   "model": None, "status": "local", "measurement": "local",
                   "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                   "cached_input_tokens": 0, "reasoning_output_tokens": 0, "context_estimates": {}}]
        for stage in ("stage_2", "stage_3", "main_agent"):
            calls = [item for item in self.calls if item["stage"] == stage]
            stages.extend(calls or [{"stage": stage, "call": 0, "label": _LABELS[stage],
                "model": None, "status": "not_used", "measurement": "local",
                "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                "cached_input_tokens": 0, "reasoning_output_tokens": 0, "context_estimates": {}}])
        kinds = {item["measurement"] for item in self.calls}
        totals = {}
        for field in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "reasoning_output_tokens"):
            totals[field] = (sum(item[field] for item in self.calls)
                             if all(item[field] is not None for item in self.calls) else None)
        return {"stages": stages, "totals": {**totals, "model_calls": len(self.calls),
                "measurement": "mixed" if len(kinds) > 1 else next(iter(kinds), "local")},
                "estimate_method": "UTF-8 bytes divided by 4; rough estimate, not billing usage.",
                "note": "Reported counts come from API usage. Estimates omit protocol overhead and hidden output. Cached input and reasoning output are subsets, not extra tokens. Retries count separately."}

    def unavailable(self, stage, parameters):
        ordinal = 1 + sum(item["stage"] == stage for item in self.calls)
        self.calls.append({"stage": stage, "call": ordinal, "label": _LABELS.get(stage, "Model call"),
            "model": parameters.get("model") if isinstance(parameters.get("model"), str) else None,
            "status": "usage_unavailable", "measurement": "unavailable",
            "input_tokens": None, "output_tokens": None, "total_tokens": None,
            "cached_input_tokens": None, "reasoning_output_tokens": None, "context_estimates": {}})


@contextmanager
def token_usage_session(*, enabled=True):
    usage = TokenUsage() if enabled else None
    token = _CURRENT_USAGE.set(usage)
    try:
        yield usage
    finally:
        _CURRENT_USAGE.reset(token)


def parse_with_usage(client, stage, **parameters):
    """Wrap the existing call unchanged; telemetry must not break the request."""
    response = None
    try:
        response = client.responses.parse(**parameters)
        return response
    finally:
        usage = _CURRENT_USAGE.get()
        if usage is not None:
            try:
                usage.record(stage, parameters, response)
            except (TypeError, ValueError, AttributeError, KeyError):
                # No private request/error content is logged or stored.
                usage.unavailable(stage, parameters)
