import json

import pytest

from bikefinder_rag.agent.sql_rag_adapters import GeminiAdapter, OllamaAdapter, OpenAIResponsesAdapter, OpenRouterAdapter


class Response:
    status_code = 200

    def __init__(self, value):
        self.value = value

    def json(self):
        return self.value


class Transport:
    def __init__(self, reply):
        self.reply = reply
        self.sent = []

    def post(self, url, **kwargs):
        self.sent.append((url, kwargs))
        return Response(self.reply)

    def close(self):
        pass


def test_ollama_tool_arguments_and_native_history():
    native = {"role": "assistant", "content": "", "thinking": "kept", "tool_calls": [{"function": {"name": "describe_catalog", "arguments": {}}}]}
    transport = Transport({"message": native, "prompt_eval_count": 10, "eval_count": 4})
    adapter = OllamaAdapter("test", session=transport)
    first = adapter.complete([{"role": "user", "content": "question"}], 2)
    adapter.complete([{"role": "assistant", "content": "", "native": first.native}, {"role": "tool", "name": "describe_catalog", "call_id": first.calls[0].id, "content": "{}"}], 2)
    sent = transport.sent[-1][1]["json"]
    assert sent["messages"][0] == native
    assert sent["messages"][1]["tool_name"] == "describe_catalog"
    assert len(sent["tools"]) == 7
    assert sent["tools"][-1]["function"]["name"] == "submit_answer"


def test_responses_preserves_reasoning_and_call_ids_without_storing():
    native = [{"type": "reasoning", "id": "r1", "encrypted_content": "encrypted", "summary": []},
              {"type": "function_call", "id": "f1", "call_id": "call1", "name": "describe_catalog", "arguments": "{}"}]
    transport = Transport({"output": native, "usage": {"input_tokens": 8, "output_tokens": 5}})
    adapter = OpenAIResponsesAdapter(key="test", session=transport)
    first = adapter.complete([{"role": "user", "content": "q"}], 2)
    adapter.complete([{"role": "system", "content": "s"}, {"role": "assistant", "content": "", "native": first.native},
                      {"role": "tool", "name": "describe_catalog", "call_id": "call1", "content": "{}"}], 2)
    body = transport.sent[-1][1]["json"]
    assert body["input"][:2] == native
    assert body["input"][2]["call_id"] == "call1"
    assert body["store"] is False
    assert all(t["strict"] is False for t in body["tools"])


def test_gemini_preserves_thought_signatures_and_grouped_function_responses():
    native = {"role": "model", "parts": [{"functionCall": {"name": "describe_catalog", "args": {}, "id": "call1"}, "thoughtSignature": "signature"}]}
    transport = Transport({"candidates": [{"content": native, "finishReason": "STOP"}]})
    adapter = GeminiAdapter(key="test", session=transport)
    first = adapter.complete([{"role": "user", "content": "q"}], 2)
    adapter.complete([{"role": "assistant", "content": "", "native": first.native},
                      {"role": "tool", "name": "describe_catalog", "call_id": "call1", "content": "{}"}], 2)
    body = transport.sent[-1][1]["json"]
    assert body["contents"][0] == native
    assert body["contents"][1]["parts"][0]["functionResponse"]["id"] == "call1"
    assert "parametersJsonSchema" in body["tools"][0]["functionDeclarations"][0]


def test_openrouter_is_explicit_and_preserves_actual_cost_and_model():
    transport = Transport({"model": "openai/gpt-6-luna", "usage": {"prompt_tokens": 4, "completion_tokens": 3, "cost": .0001},
        "choices": [{"message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}]})
    adapter = OpenRouterAdapter("openai/gpt-6-luna", key="test", session=transport)
    result = adapter.complete([{"role": "user", "content": "q"}], 2)
    assert result.usage["cost_usd"] == .0001
    assert result.model == "openai/gpt-6-luna"
    assert transport.sent[0][1]["json"]["provider"]["allow_fallbacks"] is False
    assert len(transport.sent) == 1


@pytest.mark.parametrize("host", ["https://example.com", "http://example.com", "http://user:pw@127.0.0.1", "http://127.0.0.1/path"])
def test_local_adapter_cannot_silently_send_the_corpus_remotely(host):
    with pytest.raises(ValueError):
        OllamaAdapter("test", host=host)
