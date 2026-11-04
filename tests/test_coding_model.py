"""Consumer-visible boundaries of the local tool-calling model adapter.

Every case runs against an in-process ``httpx.MockTransport`` Ollama: no
sockets, no model weights, no cloud and no token spend. The real Qwen3 tool
loop is exercised against a provisioned local server after integration.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from oryveta_engine.coding_contract import (
    CodingError, ModelReply, ModelSpec, ToolCall, strict_json,
)
from oryveta_engine.coding_model import (
    MAX_CONTENT_BYTES, LocalToolModel, prompt_bound,
)
from oryveta_engine.model_runtime import MAX_PROVIDER_RESPONSE_BYTES

MODEL = "qwen3:8b"
DIGEST = "b" * 64
LOCAL_SIZE = 5_000_000_000

TOOLS = [
    {"type": "function",
     "function": {"name": "read_file", "description": "Read an allowlisted source file",
                  "parameters": {"type": "object", "required": ["path"],
                                 "properties": {"path": {"type": "string"}}}}},
    {"type": "function",
     "function": {"name": "edit_file",
                  "parameters": {"type": "object", "required": ["path", "content"],
                                 "properties": {"path": {"type": "string"},
                                                "content": {"type": "string"}}}}},
]
MESSAGES = [{"role": "system", "content": "Repair the snapshot with the offered tools."},
            {"role": "user", "content": "The reproducer prints 3 instead of 4."}]
READ_CALL = {"type": "function",
             "function": {"index": 0, "name": "read_file",
                          "arguments": {"path": "src/app.py"}}}
EDIT_CALL = {"type": "function",
             "function": {"index": 1, "name": "edit_file",
                          "arguments": {"path": "src/app.py", "content": "total = 4\n"}}}


def tags(digest: str = DIGEST, size: int = LOCAL_SIZE, **extra) -> dict:
    entry = {"name": MODEL, "model": MODEL, "digest": digest, "size": size,
             "modified_at": "2026-10-31T10:00:00Z", **extra}
    return {"models": [{"name": "other:1b", "model": "other:1b", "digest": "c" * 64,
                        "size": LOCAL_SIZE}, entry]}


def show(capabilities=("completion", "tools", "thinking"), **extra) -> dict:
    return {"capabilities": list(capabilities), "details": {"family": "qwen3"}, **extra}


def chat(content: str = "", calls=None, **extra) -> dict:
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    body = {"model": MODEL, "created_at": "2026-10-31T10:00:01Z", "message": message,
            "done": True, "done_reason": "stop", "total_duration": 12345,
            "prompt_eval_count": 120, "eval_count": 40}
    body.update(extra)
    return body


def with_message(**fields) -> dict:
    body = chat("edited the file")
    body["message"].update(fields)
    return body


def with_calls(calls) -> dict:
    return chat("", calls)


class FakeOllama:
    """Deterministic in-process Ollama. Unexpected endpoints fail the test."""

    def __init__(self, *, tags_bodies=None, show_body=None, chat_bodies=None,
                 chat_status: int = 200, chat_raw: bytes | None = None, errors=None):
        self.tags_bodies = list(tags_bodies) if tags_bodies else [tags()]
        self.show_body = show() if show_body is None else show_body
        self.chat_bodies = list(chat_bodies) if chat_bodies else [chat("edited the file")]
        self.chat_status = chat_status
        self.chat_raw = chat_raw
        self.errors = dict(errors or {})
        self.requests: list[tuple[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((path, strict_json(request.content) if request.content else None))
        if path in self.errors:
            raise self.errors[path]
        if path == "/api/tags":
            return httpx.Response(200, json=_next(self.tags_bodies))
        if path == "/api/show":
            return httpx.Response(200, json=self.show_body)
        if path == "/api/chat":
            if self.chat_raw is not None:
                return httpx.Response(200, content=self.chat_raw)
            if self.chat_status != 200:
                return httpx.Response(self.chat_status,
                                      json={"error": "undisclosed upstream detail"})
            return httpx.Response(200, json=_next(self.chat_bodies))
        raise AssertionError(f"the adapter must never call {path}")


def _next(queue: list):
    return queue[0] if len(queue) == 1 else queue.pop(0)


def build(fake: FakeOllama, **spec_fields) -> LocalToolModel:
    return LocalToolModel(ModelSpec(MODEL, DIGEST, **spec_fields),
                          transport=httpx.MockTransport(fake))


def run_turn(model: LocalToolModel, messages=None, tools=None, *, max_output_tokens=256,
             timeout_seconds=30) -> ModelReply:
    return asyncio.run(model.turn(list(MESSAGES) if messages is None else messages,
                                  TOOLS if tools is None else tools,
                                  max_output_tokens=max_output_tokens,
                                  timeout_seconds=timeout_seconds))


def paths(fake: FakeOllama) -> list[str]:
    return [path for path, _ in fake.requests]


def test_verify_reports_the_observed_local_model():
    fake = FakeOllama()
    observed = asyncio.run(build(fake).verify())
    assert observed == {"name": MODEL, "digest": DIGEST,
                        "capabilities": ("completion", "tools", "thinking")}
    assert paths(fake) == ["/api/tags", "/api/show"]
    assert fake.requests[1][1] == {"model": MODEL}


@pytest.mark.parametrize("catalog,code", [
    ({"models": []}, "model_unavailable"),
    ({"models": [{"name": "other:1b", "digest": "c" * 64, "size": LOCAL_SIZE}]},
     "model_unavailable"),
    (tags(digest="e" * 64), "model_changed"),
    (tags(digest="sha256:" + "e" * 64), "model_changed"),
    (tags(size=4096), "model_unavailable"),
    (tags(size=None), "model_unavailable"),
    (tags(remote_model="qwen3-coder:480b-cloud"), "model_unavailable"),
    (tags(remote_host="https://ollama.com"), "model_unavailable"),
    (tags(remote=True), "model_unavailable"),
    (tags(digest="not-a-sha256-digest"), "provider_contract"),
    ({"models": {"name": MODEL}}, "provider_contract"),
    ({"models": ["qwen3:8b"]}, "provider_contract"),
    ({}, "provider_contract"),
])
def test_verify_requires_one_pinned_local_installation(catalog, code):
    fake = FakeOllama(tags_bodies=[catalog])
    with pytest.raises(CodingError) as error:
        asyncio.run(build(fake).verify())
    assert error.value.code == code
    assert paths(fake) == ["/api/tags"]


def test_verify_accepts_a_catalog_entry_with_a_prefixed_digest():
    fake = FakeOllama(tags_bodies=[tags(digest="sha256:" + DIGEST)])
    assert asyncio.run(build(fake).verify())["digest"] == DIGEST


def test_native_ollama_call_identifiers_are_accepted():
    native = {"id": "call_native-123", "function": READ_CALL["function"]}
    response = run_turn(build(FakeOllama(chat_bodies=[chat(calls=[native])])))
    assert response.calls == (ToolCall("read_file", {"path": "src/app.py"}),)


def test_content_completion_can_have_an_empty_call_list():
    response = run_turn(build(FakeOllama(chat_bodies=[chat("Finished", calls=[])])))
    assert response.content == "Finished"
    assert response.calls == ()


@pytest.mark.parametrize("details,code", [
    (show(capabilities=("completion",)), "model_unavailable"),
    (show(capabilities=("completion", "thinking")), "model_unavailable"),
    (show(capabilities=("completion", "tools", "cloud")), "model_unavailable"),
    (show(capabilities=("completion", "tools", "remote")), "model_unavailable"),
    (show(remote_host="https://ollama.com"), "model_unavailable"),
    (show(remote_model="qwen3-coder:480b"), "model_unavailable"),
    (show(capabilities=()), "provider_contract"),
    ({"capabilities": "tools"}, "provider_contract"),
    ({"capabilities": ["tools", 7]}, "provider_contract"),
    ({}, "provider_contract"),
])
def test_verify_requires_local_native_tool_calling(details, code):
    fake = FakeOllama(show_body=details)
    with pytest.raises(CodingError) as error:
        asyncio.run(build(fake).verify())
    assert error.value.code == code
    assert paths(fake) == ["/api/tags", "/api/show"]


@pytest.mark.parametrize("name", ["gemma4:cloud", "qwen3-coder:480b-cloud", "deepseek-v3-cloud"])
def test_cloud_model_names_are_refused_before_any_request(name):
    fake = FakeOllama()
    with pytest.raises(CodingError) as error:
        LocalToolModel(ModelSpec(name, DIGEST), transport=httpx.MockTransport(fake))
    assert error.value.code == "invalid_config"
    assert fake.requests == []


@pytest.mark.parametrize("spec", [
    ModelSpec(MODEL, DIGEST, "http://evil.example:11434"),
    ModelSpec(MODEL, DIGEST, "https://127.0.0.1:11434"),
    ModelSpec(MODEL, DIGEST, "http://127.0.0.1:1234"),
    ModelSpec(MODEL, DIGEST, "http://127.0.0.1:11434/proxy"),
    ModelSpec(MODEL, DIGEST, "http://user:pass@127.0.0.1:11434"),
    ModelSpec(MODEL, DIGEST, "http://169.254.169.254:11434"),
    ModelSpec("../escape", DIGEST),
    ModelSpec(MODEL, "not-a-digest"),
    ModelSpec(MODEL, DIGEST, "http://127.0.0.1:11434", 16384, 16384),
])
def test_unapproved_specs_are_refused_before_any_request(spec):
    fake = FakeOllama()
    with pytest.raises(CodingError) as error:
        LocalToolModel(spec, transport=httpx.MockTransport(fake))
    assert error.value.code == "invalid_config"
    assert fake.requests == []


def test_turn_performs_a_native_tool_calling_round():
    fake = FakeOllama(chat_bodies=[chat("Reading the failing file.", [READ_CALL, EDIT_CALL])])
    reply = run_turn(build(fake))
    assert reply == ModelReply(
        "Reading the failing file.",
        (ToolCall("read_file", {"path": "src/app.py"}),
         ToolCall("edit_file", {"path": "src/app.py", "content": "total = 4\n"})), 120, 40)
    assert paths(fake) == ["/api/tags", "/api/chat", "/api/tags"]
    payload = fake.requests[1][1]
    assert payload["model"] == MODEL
    assert payload["stream"] is False and payload["think"] is False
    assert payload["options"] == {"temperature": 0, "num_ctx": 16384, "num_predict": 256}
    assert payload["tools"] == TOOLS
    assert payload["messages"] == MESSAGES
    assert set(payload) == {"model", "messages", "stream", "think", "options", "tools"}


def test_turn_accepts_native_tool_results_and_a_content_only_completion():
    messages = MESSAGES + [
        {"role": "assistant", "content": "", "tool_calls": [READ_CALL]},
        {"role": "tool", "tool_name": "read_file", "content": "total = 3\n"},
    ]
    fake = FakeOllama(chat_bodies=[chat("The reproducer now prints 4.")])
    reply = run_turn(build(fake), messages=messages, tools=[])
    assert reply == ModelReply("The reproducer now prints 4.", (), 120, 40)
    assert fake.requests[1][1]["messages"] == messages
    assert "tools" not in fake.requests[1][1]


def test_turn_omits_absent_tool_call_arguments_as_an_empty_object():
    call = {"type": "function", "function": {"name": "read_file"}}
    fake = FakeOllama(chat_bodies=[with_calls([call])])
    assert run_turn(build(fake)).calls == (ToolCall("read_file", {}),)


def test_turn_detects_model_replacement_before_the_call():
    fake = FakeOllama(tags_bodies=[tags(digest="e" * 64)])
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "model_changed"
    assert paths(fake) == ["/api/tags"]


def test_turn_detects_model_replacement_after_the_call_and_discards_the_reply():
    fake = FakeOllama(tags_bodies=[tags(), tags(digest="e" * 64)],
                      chat_bodies=[chat("edited the file", [EDIT_CALL])])
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "model_changed"
    assert paths(fake) == ["/api/tags", "/api/chat", "/api/tags"]


@pytest.mark.parametrize("body", [
    chat("hello", model="other:1b"),
    chat("hello", model=None),
])
def test_turn_rejects_a_reply_from_another_model(body):
    fake = FakeOllama(chat_bodies=[body])
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "model_changed"


def test_turn_rejects_an_oversized_reply_without_echoing_it():
    padding = b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 1)
    fake = FakeOllama(chat_raw=b'{"padding":"' + padding + b'"}')
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "provider_contract"
    assert "padding" not in str(error.value) and "xxxx" not in str(error.value)


@pytest.mark.parametrize("raw", [
    b'{"done": true, "done": true}',
    b"not json at all",
    b'["done"]',
    b"",
])
def test_turn_rejects_unusable_reply_bytes(raw):
    fake = FakeOllama(chat_raw=raw)
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "provider_contract"


@pytest.mark.parametrize("body", [
    chat("hello", done=False),
    chat("hello", done="true"),
    chat("hello", done_reason="length"),
    chat("hello", done_reason=7),
    with_message(role="user"),
    with_message(role="tool"),
    with_message(thinking="the operator must not see this"),
    with_message(images=["QUJD"]),
    with_message(secret="unsupported field"),
    with_message(content=42),
    with_message(content="x" * (MAX_CONTENT_BYTES + 1)),
    with_calls(None),
    chat("   "),
    chat("hello", message="not an object"),
    chat("hello", message=None),
    chat("hello", prompt_eval_count=None),
    chat("hello", eval_count=None),
    chat("hello", prompt_eval_count=True),
    chat("hello", eval_count=True),
    chat("hello", eval_count=257),
    chat("hello", eval_count=-1),
    chat("hello", prompt_eval_count=1_000_000),
    with_calls("read_file"),
    with_calls([]),
    with_calls([READ_CALL] * 9),
    with_calls([{"type": "function", "function": {"name": "delete_everything",
                                                  "arguments": {}}}]),
    with_calls([{"type": "custom", "function": {"name": "read_file", "arguments": {}}}]),
    with_calls([{"type": "function", "function": {"name": "read_file",
                                                  "arguments": '{"path": "src/app.py"}'}}]),
    with_calls([{"type": "function", "function": {"name": "read_file", "arguments": None}}]),
    with_calls([{"type": "function", "function": {"name": 7, "arguments": {}}}]),
    with_calls([{"type": "function", "function": {"name": "read_file", "arguments": {},
                                                  "index": 9}}]),
    with_calls([{"type": "function", "function": {"name": "read_file", "arguments": {},
                                                  "index": "0"}}]),
    with_calls([{"type": "function", "function": {
        "name": "edit_file", "arguments": {"path": "src/app.py", "content": "x" * 9000}}}]),
    with_calls([{"function": {"name": "read_file", "arguments": {}}, "extra": 1}]),
])
def test_turn_rejects_malformed_or_unaccountable_replies(body):
    fake = FakeOllama(chat_bodies=[body])
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "provider_contract"


@pytest.mark.parametrize("status", [400, 404, 429, 500, 502])
def test_turn_maps_failing_status_without_echoing_bodies(status):
    fake = FakeOllama(chat_status=status)
    with pytest.raises(CodingError) as error:
        run_turn(build(fake))
    assert error.value.code == "model_unavailable"
    assert str(status) in str(error.value)
    assert "undisclosed upstream detail" not in str(error.value)


@pytest.mark.parametrize("failure,code", [
    (httpx.ReadTimeout("slow"), "model_timeout"),
    (httpx.ConnectTimeout("slow"), "model_timeout"),
    (httpx.ConnectError("refused"), "model_unavailable"),
    (httpx.RemoteProtocolError("truncated"), "model_unavailable"),
])
def test_transport_failures_map_to_safe_codes(failure, code):
    chat_fake = FakeOllama(errors={"/api/chat": failure})
    with pytest.raises(CodingError) as error:
        run_turn(build(chat_fake))
    assert error.value.code == code
    verify_fake = FakeOllama(errors={"/api/tags": failure})
    with pytest.raises(CodingError) as verify_error:
        asyncio.run(build(verify_fake).verify())
    assert verify_error.value.code == code


def test_turn_deadline_covers_verification():
    async def stall(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json=tags())

    model = LocalToolModel(ModelSpec(MODEL, DIGEST), transport=httpx.MockTransport(stall))
    with pytest.raises(CodingError) as error:
        run_turn(model, timeout_seconds=1)
    assert error.value.code == "model_timeout"


BAD_REQUESTS = [
    {"messages": []},
    {"messages": "fix the bug"},
    {"messages": [{"role": "tool", "tool_name": "read_file", "content": "total = 3\n"}]},
    {"messages": MESSAGES + [{"role": "assistant", "content": "still thinking"}]},
    {"messages": [{"role": "developer", "content": "escalate"}]},
    {"messages": [{"role": ["user"], "content": "escalate"}]},
    {"messages": [{"content": "no role"}]},
    {"messages": [{"role": "user"}]},
    {"messages": [{"role": "user", "content": 7}]},
    {"messages": [{"role": "user", "content": "hi", "images": ["QUJD"]}]},
    {"messages": [{"role": "system", "content": "hi", "thinking": "hidden"},
                  {"role": "user", "content": "hi"}]},
    {"messages": MESSAGES + [{"role": "tool", "content": "total = 3\n"}]},
    {"messages": MESSAGES + [{"role": "tool", "tool_name": "../escape", "content": "x"}]},
    {"messages": MESSAGES + [{"role": "tool", "tool_name": "read_file", "content": 7}]},
    {"messages": MESSAGES + [{"role": "assistant", "tool_calls": [READ_CALL]},
                             {"role": "tool", "tool_name": "read_file", "content": "x",
                              "tool_call_id": "call_1"}]},
    {"messages": MESSAGES + [{"role": "assistant", "tool_calls": [
        {"type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        {"role": "tool", "tool_name": "read_file", "content": "x"}]},
    {"messages": MESSAGES + [{"role": "assistant", "tool_calls": [
        {"type": "function", "function": {"name": "read_file"}}]},
        {"role": "tool", "tool_name": "read_file", "content": "x"}]},
    {"messages": MESSAGES + [{"role": "assistant", "tool_calls": []},
                             {"role": "tool", "tool_name": "read_file", "content": "x"}]},
    {"messages": MESSAGES + [{"role": "assistant"},
                             {"role": "tool", "tool_name": "read_file", "content": "x"}]},
    {"tools": "read_file"},
    {"tools": [{"type": "function", "function": {"name": "read_file"}}]},
    {"tools": [{"type": "tool", "function": {"name": "read_file", "parameters": {}}}]},
    {"tools": [{"function": {"name": "read_file", "parameters": {}}}]},
    {"tools": [{"type": "function", "function": {"name": "read_file", "parameters": {},
                                                 "strict": True}}]},
    {"tools": [{"type": "function", "function": {"name": "read file", "parameters": {}}}]},
    {"tools": [TOOLS[0], TOOLS[0]]},
    {"tools": TOOLS * 9},
    {"max_output_tokens": 0},
    {"max_output_tokens": -1},
    {"max_output_tokens": 1025},
    {"max_output_tokens": True},
    {"max_output_tokens": 256.0},
    {"timeout_seconds": 0},
    {"timeout_seconds": 601},
    {"timeout_seconds": float("nan")},
    {"timeout_seconds": "30"},
]


@pytest.mark.parametrize("override", BAD_REQUESTS)
def test_turn_refuses_controller_request_violations(override):
    fake = FakeOllama()
    call = {"messages": list(MESSAGES), "tools": TOOLS, "max_output_tokens": 256,
            "timeout_seconds": 30, **override}
    with pytest.raises(CodingError) as error:
        asyncio.run(build(fake).turn(call["messages"], call["tools"],
                                     max_output_tokens=call["max_output_tokens"],
                                     timeout_seconds=call["timeout_seconds"]))
    assert error.value.code == "invalid_request"
    assert fake.requests == []




def test_turn_refuses_a_prompt_that_was_never_reserved():
    oversized = MESSAGES + [{"role": "user", "content": "x" * 1500}]
    assert prompt_bound(oversized, TOOLS) + 1024 > 2048
    fake = FakeOllama()
    model = build(fake, context_tokens=2048, output_tokens=1024)
    with pytest.raises(CodingError) as error:
        asyncio.run(model.turn(oversized, TOOLS, max_output_tokens=1024, timeout_seconds=30))
    assert error.value.code == "invalid_request"
    assert fake.requests == []
    # The same prompt is admitted once the reservation fits the configured context.
    assert run_turn(build(fake), messages=oversized).content == "edited the file"


def test_usage_is_checked_against_the_reservation_not_the_context():
    bound = prompt_bound(MESSAGES, TOOLS)
    fake = FakeOllama(chat_bodies=[chat("edited the file", prompt_eval_count=bound)])
    assert run_turn(build(fake)).input_tokens == bound
    over = FakeOllama(chat_bodies=[chat("edited the file", prompt_eval_count=bound + 1)])
    with pytest.raises(CodingError) as error:
        run_turn(build(over))
    assert error.value.code == "provider_contract"
