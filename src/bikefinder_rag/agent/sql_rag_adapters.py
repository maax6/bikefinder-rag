"""Small provider adapters; all tool execution remains in the common service.

Wire histories retain provider-native tool IDs, reasoning items and Gemini
thought signatures. Adapters never load evaluation references or retry calls.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from urllib.parse import urlparse

import requests

from bikefinder_rag.agent.sql_rag_contract import TOOLS
from bikefinder_rag.agent.sql_rag_output import SUBMIT_ANSWER

WIRE_TOOLS = [*TOOLS, SUBMIT_ANSWER]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    text: str
    calls: list[ToolCall]
    native: object
    usage: dict
    model: str
    finish_reason: str | None = None


def arguments(value):
    # Invalid provider arguments remain invalid tool inputs, never silently {}.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def description(tool):
    return tool["description"] + " " + " ".join(tool.get("semantics", {}).get("rules", []))


def chat_tools():
    return [{"type": "function", "function": {"name": t["name"], "description": description(t),
            "parameters": deepcopy(t["input_schema"])}} for t in WIRE_TOOLS]


class HTTPAdapter:
    def __init__(self, model, *, session=None):
        self.model = model
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False

    def _post(self, url, payload, headers, timeout):
        response = self.session.post(url, json=payload, headers=headers, timeout=max(.1, timeout), allow_redirects=False)
        if response.status_code >= 400:
            # Never include response bodies/headers/keys in exception receipts.
            raise RuntimeError(f"{self.provider} HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"{self.provider} unexpected HTTP {response.status_code}")
        return response.json()

    def metadata(self):
        return {"provider": self.provider, "model": self.model, "settings": deepcopy(self.settings)}

    def close(self):
        self.session.close()


class OllamaAdapter(HTTPAdapter):
    provider = "ollama"

    def __init__(self, model, *, host="http://127.0.0.1:11434", session=None, max_tokens=1200, num_ctx=16384, think=False):
        super().__init__(model, session=session)
        parsed = urlparse(host)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Local adapter requires a loopback Ollama HTTP endpoint")
        self.host = host.rstrip("/")
        self.settings = {"num_ctx": num_ctx, "num_predict": max_tokens, "temperature": 0, "think": think}

    def warmup(self, prompt, timeout=60):
        """Prepare the generic prompt/tools prefix, never an evaluation question."""
        raw = self._post(self.host + "/api/chat", {"model": self.model,
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": "Préparation du service."}],
            "tools": chat_tools(), "stream": False, "keep_alive": "10m", "think": self.settings["think"],
            "options": {"num_ctx": self.settings["num_ctx"], "num_predict": 1, "temperature": 0}}, {}, timeout)
        return {"model": raw.get("model"), "total_seconds": raw.get("total_duration", 0) / 1e9,
                "load_seconds": raw.get("load_duration", 0) / 1e9, "input_tokens": raw.get("prompt_eval_count")}

    def complete(self, messages, timeout):
        history = []
        for m in messages:
            if m["role"] == "assistant" and m.get("native") is not None:
                history.append(deepcopy(m["native"]))
            elif m["role"] == "tool":
                history.append({"role": "tool", "tool_name": m["name"], "content": m["content"]})
            else:
                history.append({"role": m["role"], "content": m["content"]})
        payload = {"model": self.model, "messages": history, "tools": chat_tools(), "stream": False,
                   "keep_alive": "10m", "think": self.settings["think"],
                   "options": {k: v for k, v in self.settings.items() if k != "think"}}
        raw = self._post(self.host + "/api/chat", payload, {}, timeout)
        native = raw["message"]
        calls = [ToolCall(str(c.get("id") or f"ollama-{len(messages)}-{i}"), c["function"]["name"], arguments(c["function"]["arguments"]))
                 for i, c in enumerate(native.get("tool_calls", []))]
        return Completion(native.get("content", ""), calls, native,
            {"input_tokens": raw.get("prompt_eval_count"), "output_tokens": raw.get("eval_count"), "cost_usd": None,
             "load_seconds": raw.get("load_duration", 0) / 1e9, "native_model_seconds": raw.get("total_duration", 0) / 1e9},
             raw.get("model", self.model), raw.get("done_reason"))


class OpenAIResponsesAdapter(HTTPAdapter):
    provider = "openai_responses"

    def __init__(self, model="gpt-6-luna", *, key=None, session=None, max_tokens=1200, effort="none"):
        super().__init__(model, session=session)
        self.key = key or os.getenv("OPENAI_API_KEY")
        self.settings = {"max_output_tokens": max_tokens, "reasoning_effort": effort, "store": False}

    def complete(self, messages, timeout):
        if not self.key:
            raise RuntimeError("OPENAI_API_KEY unavailable")
        items = []
        system = []
        for m in messages:
            if m["role"] == "system":
                system.append(m["content"])
            elif m["role"] == "assistant" and m.get("native") is not None:
                items.extend(deepcopy(m["native"]))
            elif m["role"] == "tool":
                items.append({"type": "function_call_output", "call_id": m["call_id"], "output": m["content"]})
            else:
                items.append({"role": m["role"], "content": m["content"]})
        tools = [{"type": "function", "name": t["name"], "description": description(t),
                  "parameters": deepcopy(t["input_schema"]), "strict": False} for t in WIRE_TOOLS]
        raw = self._post("https://api.openai.com/v1/responses", {"model": self.model, "instructions": "\n".join(system),
            "input": items, "tools": tools, "store": False, "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": self.settings["reasoning_effort"]}, "max_output_tokens": self.settings["max_output_tokens"]},
            {"Authorization": "Bearer " + self.key}, timeout)
        output = raw.get("output", [])
        calls = [ToolCall(c["call_id"], c["name"], arguments(c["arguments"])) for c in output if c.get("type") == "function_call"]
        text = "".join(p.get("text", "") for c in output if c.get("type") == "message" for p in c.get("content", []) if p.get("type") == "output_text")
        usage = raw.get("usage") or {}
        return Completion(text, calls, output, {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"), "cost_usd": None},
                          raw.get("model", self.model), raw.get("status"))


class GeminiAdapter(HTTPAdapter):
    provider = "gemini"

    def __init__(self, model="gemini-3.8-flash", *, key=None, session=None, max_tokens=1200):
        super().__init__(model, session=session)
        if not all(c.isalnum() or c in "-_." for c in model):
            raise ValueError("Invalid Gemini model ID")
        self.key = key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.settings = {"maxOutputTokens": max_tokens, "temperature": 0}

    def complete(self, messages, timeout):
        if not self.key:
            raise RuntimeError("GEMINI_API_KEY unavailable")
        contents, system = [], []
        for m in messages:
            if m["role"] == "system":
                system.append(m["content"])
                continue
            if m["role"] == "assistant" and m.get("native") is not None:
                content = deepcopy(m["native"])
            elif m["role"] == "tool":
                response = {"name": m["name"], "response": json.loads(m["content"])}
                native_ids = {p["functionCall"].get("id") for previous in messages if previous["role"] == "assistant" and previous.get("native")
                              for p in previous["native"].get("parts", []) if "functionCall" in p}
                if m["call_id"] in native_ids:
                    response["id"] = m["call_id"]
                content = {"role": "user", "parts": [{"functionResponse": response}]}
            else:
                content = {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            # Group consecutive function results into one user turn, preserve signature parts.
            if contents and content["role"] == contents[-1]["role"]:
                contents[-1]["parts"].extend(content["parts"])
            else:
                contents.append(content)
        raw = self._post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
            {"systemInstruction": {"parts": [{"text": "\n".join(system)}]}, "contents": contents,
             "tools": [{"functionDeclarations": [{"name": t["name"], "description": description(t), "parametersJsonSchema": deepcopy(t["input_schema"])} for t in WIRE_TOOLS]}],
             "generationConfig": self.settings}, {"x-goog-api-key": self.key}, timeout)
        candidates = raw.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidate")
        native = candidates[0]["content"]
        calls = [ToolCall(p["functionCall"].get("id") or f"gemini-{len(messages)}-{i}", p["functionCall"]["name"], p["functionCall"].get("args", {}))
                 for i, p in enumerate(native.get("parts", [])) if "functionCall" in p]
        text = "".join(p.get("text", "") for p in native.get("parts", []) if not p.get("thought"))
        usage = raw.get("usageMetadata") or {}
        return Completion(text, calls, native, {"input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"), "reasoning_tokens": usage.get("thoughtsTokenCount"), "cost_usd": None}, self.model, candidates[0].get("finishReason"))


class OpenRouterAdapter(HTTPAdapter):
    """Explicit alternative transport for the same model, not a hidden fallback."""
    provider = "openrouter"

    def __init__(self, model, *, key=None, session=None, max_tokens=1200, effort="none"):
        super().__init__(model, session=session)
        self.key = key or os.getenv("OPENROUTER_API_KEY")
        self.settings = {"max_tokens": max_tokens, "reasoning_effort": effort, "allow_fallbacks": False}

    def complete(self, messages, timeout):
        if not self.key:
            raise RuntimeError("OPENROUTER_API_KEY unavailable")
        history = []
        for m in messages:
            if m["role"] == "assistant" and m.get("native") is not None:
                history.append(deepcopy(m["native"]))
            elif m["role"] == "tool":
                history.append({"role": "tool", "tool_call_id": m["call_id"], "content": m["content"]})
            else:
                history.append({"role": m["role"], "content": m["content"]})
        raw = self._post("https://openrouter.ai/api/v1/chat/completions", {"model": self.model, "messages": history,
            "tools": chat_tools(), "stream": False, "max_tokens": self.settings["max_tokens"],
            "reasoning": {"effort": self.settings["reasoning_effort"]}, "provider": {"allow_fallbacks": False, "require_parameters": True}},
            {"Authorization": "Bearer " + self.key}, timeout)
        choice = raw["choices"][0]
        native = choice["message"]
        calls = [ToolCall(c["id"], c["function"]["name"], arguments(c["function"]["arguments"])) for c in native.get("tool_calls", [])]
        usage = raw.get("usage") or {}
        return Completion(native.get("content") or "", calls, native,
            {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"), "cost_usd": usage.get("cost"),
             "request_id": raw.get("id"), "upstream_provider": raw.get("provider")}, raw.get("model", self.model), choice.get("finish_reason"))


def create_adapter(provider, model, **kwargs):
    constructors = {"ollama": OllamaAdapter, "openai_responses": OpenAIResponsesAdapter,
                    "gemini": GeminiAdapter, "openrouter": OpenRouterAdapter}
    if provider not in constructors:
        raise ValueError("Unsupported provider")
    return constructors[provider](model, **kwargs)
