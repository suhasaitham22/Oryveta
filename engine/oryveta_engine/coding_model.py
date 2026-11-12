"""Digest-pinned local Ollama inference for scoped tools and typed role outputs.

The model is a bounded suggestion source, never an authority: it never selects
the endpoint, the served model, the runner image, a command or an expected
value. This adapter speaks to exactly one operator-approved loopback Ollama
origin using native ``/api/chat`` tool calls or an exclusive JSON-schema format,
refuses cloud-backed or replaced models, and rejects unaccountable replies.

A loopback origin alone is not proof of local inference, because an Ollama
server can proxy cloud models. Verification therefore also requires a
substantive locally installed catalog entry with the pinned digest and no
remote/cloud markers, and it never pulls a model.

Failure codes (``CodingError``; messages never carry upstream bodies or secrets):

* ``invalid_config``    operator model spec or endpoint is not approved.
* ``invalid_request``   the controller passed messages, tools or limits that
  violate this boundary, including a prompt that was never reserved.
* ``model_unavailable`` unreachable endpoint, failing status, missing model,
  cloud/remote-backed entry, or no native tool-calling capability.
* ``model_changed``     the installed digest or the answering model drifted.
* ``provider_contract`` malformed, oversized, truncated or unaccountable reply.
* ``model_timeout``     the bounded deadline, verification included, expired.

There is no second provider, no retry, no automatic model pull and no network
egress beyond the validated loopback origin. Thinking is disabled on every
request and a reply that still carries hidden thinking text is refused rather
than stripped, so no hidden text can reach a reply or an operator record.
"""
from __future__ import annotations

import asyncio
import math
import re
from typing import Any

import httpx

from .coding_contract import (
    CodingError, ModelReply, ModelSpec, ToolCall, canonical_json, strict_json,
)
from .model_runtime import MAX_PROVIDER_RESPONSE_BYTES, validate_local_ollama_url

MODEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,100}")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
CAPABILITY_PATTERN = re.compile(r"[a-z0-9_-]{1,64}")

FRAMING_TOKENS = 512
MAX_MESSAGES = 256
MAX_TOOLS = 16
MAX_TOOL_CALLS = 8
MAX_CONTENT_BYTES = 16384
MAX_TOOL_ARGUMENT_BYTES = 8192
MAX_CAPABILITIES = 32
MAX_CATALOG_ENTRIES = 512
VERIFY_TIMEOUT_SECONDS = 15.0
MAX_TURN_SECONDS = 600.0
# A cloud entry is a manifest of a few kilobytes; a usable local model is not.
MIN_LOCAL_MODEL_BYTES = 100 * 1024 * 1024

REMOTE_MARKERS = ("remote_model", "remote_host", "remote")
CLOUD_CAPABILITIES = frozenset({"cloud", "remote"})
MESSAGE_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "system": (frozenset({"role", "content"}), frozenset({"role", "content"})),
    "user": (frozenset({"role", "content"}), frozenset({"role", "content"})),
    "assistant": (frozenset({"role", "content", "tool_calls"}), frozenset({"role"})),
    "tool": (frozenset({"role", "tool_name", "content"}),
             frozenset({"role", "tool_name", "content"})),
}
REPLY_FIELDS = frozenset({"role", "content", "tool_calls", "thinking", "images"})


def prompt_bound(messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                 output_schema: dict[str, Any] | None = None) -> int:
    """Conservative admission bound, not an exact tokenizer measurement.

    One UTF-8 byte of the serialized native request cannot encode more than one
    token for the tokenizers in use, so serialized message and tool bytes plus a
    framing allowance keeps the controller's reservation pessimistic. The
    controller reserves this bound plus its output limit before a turn, and the
    provider-reported prompt usage is still checked against it afterwards.
    """
    try:
        size = (len(canonical_json(messages).encode("utf-8"))
                + len(canonical_json(tools).encode("utf-8")))
        if output_schema is not None:
            size += len(canonical_json(output_schema).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise CodingError("invalid_request", "request payload is not representable JSON") from None
    return size + FRAMING_TOKENS


def _request_object(value: object, allowed: frozenset[str], required: frozenset[str],
                    message: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or any(not isinstance(key, str) for key in value)
            or set(value) - allowed or required - set(value)):
        raise CodingError("invalid_request", message)
    return value


def _request_tool_calls(value: object, message: str) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_TOOL_CALLS:
        raise CodingError("invalid_request", message)
    for item in value:
        item = _request_object(item, frozenset({"type", "function"}),
                               frozenset({"function"}), message)
        if item.get("type", "function") != "function":
            raise CodingError("invalid_request", message)
        function = _request_object(item["function"], frozenset({"index", "name", "arguments"}),
                                   frozenset({"name", "arguments"}), message)
        if not isinstance(function["name"], str) or not TOOL_NAME_PATTERN.fullmatch(
                function["name"]):
            raise CodingError("invalid_request", message)
        if not isinstance(function["arguments"], dict) or any(
                not isinstance(key, str) for key in function["arguments"]):
            raise CodingError("invalid_request", message)
        if "index" in function and type(function["index"]) is not int:
            raise CodingError("invalid_request", message)


def _validate_messages(messages: object) -> list[dict[str, Any]]:
    """Accept only the native Ollama role conventions used by the repair loop."""
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise CodingError("invalid_request", "a turn needs 1 to 256 native chat messages")
    for message in messages:
        if (not isinstance(message, dict) or not isinstance(message.get("role"), str)
                or message["role"] not in MESSAGE_FIELDS):
            raise CodingError("invalid_request", "chat messages need a supported native role")
        allowed, required = MESSAGE_FIELDS[message["role"]]
        detail = f"a {message['role']} message has unsupported or missing native fields"
        message = _request_object(message, allowed, required, detail)
        if "content" in message and not isinstance(message["content"], str):
            raise CodingError("invalid_request", detail)
        if message["role"] == "tool" and (not isinstance(message["tool_name"], str)
                                          or not TOOL_NAME_PATTERN.fullmatch(
                                              message["tool_name"])):
            raise CodingError("invalid_request", detail)
        if message["role"] == "assistant":
            if "content" not in message and "tool_calls" not in message:
                raise CodingError("invalid_request", detail)
            if "tool_calls" in message:
                _request_tool_calls(message["tool_calls"], detail)
    if messages[0]["role"] not in {"system", "user"}:
        raise CodingError("invalid_request", "a turn must open with a system or user message")
    if messages[-1]["role"] not in {"user", "tool"}:
        raise CodingError("invalid_request", "a turn must end with a user or tool message")
    return messages


def _validate_tools(tools: object) -> frozenset[str]:
    """Return the offered tool names; the model may only call one of these."""
    if not isinstance(tools, list) or len(tools) > MAX_TOOLS:
        raise CodingError("invalid_request", "a turn offers at most 16 native function tools")
    names = []
    for tool in tools:
        detail = "native tool definitions need a function name and JSON Schema parameters"
        tool = _request_object(tool, frozenset({"type", "function"}),
                               frozenset({"type", "function"}), detail)
        if tool["type"] != "function":
            raise CodingError("invalid_request", detail)
        function = _request_object(tool["function"],
                                   frozenset({"name", "description", "parameters"}),
                                   frozenset({"name", "parameters"}), detail)
        if (not isinstance(function["name"], str)
                or not TOOL_NAME_PATTERN.fullmatch(function["name"])
                or not isinstance(function["parameters"], dict)
                or ("description" in function and not isinstance(function["description"], str))):
            raise CodingError("invalid_request", detail)
        names.append(function["name"])
    if len(set(names)) != len(names):
        raise CodingError("invalid_request", "native tool names must be unique")
    return frozenset(names)


def _reject_remote(entry: dict[str, Any]) -> None:
    """Refuse a model that a local server only proxies for a remote/cloud host."""
    if any(entry.get(marker) for marker in REMOTE_MARKERS):
        raise CodingError("model_unavailable",
                          "the configured model is served by a remote host, not locally")


def _reject_cloud_name(name: str) -> None:
    for part in name.split(":"):
        if part == "cloud" or part.endswith("-cloud"):
            raise CodingError("invalid_config",
                              "cloud model names cannot be served by local inference")


def _capabilities(body: dict[str, Any]) -> tuple[str, ...]:
    capabilities = body.get("capabilities")
    if (not isinstance(capabilities, list) or not 1 <= len(capabilities) <= MAX_CAPABILITIES
            or any(not isinstance(item, str) or not CAPABILITY_PATTERN.fullmatch(item)
                   for item in capabilities)):
        raise CodingError("provider_contract", "the local model advertised unusable capabilities")
    if CLOUD_CAPABILITIES.intersection(capabilities):
        raise CodingError("model_unavailable",
                          "the configured model is cloud-backed, not local inference")
    if "tools" not in capabilities:
        raise CodingError("model_unavailable",
                          "the configured model does not support native tool calling")
    return tuple(capabilities)


class LocalToolModel:
    """One operator-pinned local model, reachable only through native tool calls.

    ``transport`` is an in-process test seam. It replaces the socket layer only;
    the endpoint policy, digest pinning and reply contract still apply.
    """

    def __init__(self, spec: ModelSpec, *, transport: httpx.AsyncBaseTransport | None = None):
        if not isinstance(spec, ModelSpec):
            raise CodingError("invalid_config", "a validated operator model spec is required")
        if not isinstance(spec.name, str) or not MODEL_NAME_PATTERN.fullmatch(spec.name):
            raise CodingError("invalid_config", "invalid local model name")
        _reject_cloud_name(spec.name)
        digest = spec.digest.removeprefix("sha256:").lower() if isinstance(spec.digest, str) else ""
        if not DIGEST_PATTERN.fullmatch(digest):
            raise CodingError("invalid_config", "the model digest must be a SHA-256 digest")
        if (type(spec.context_tokens) is not int or type(spec.output_tokens) is not int
                or not 1024 <= spec.context_tokens <= 1_048_576
                or not 1 <= spec.output_tokens < spec.context_tokens - FRAMING_TOKENS):
            raise CodingError("invalid_config", "the model context and output budgets conflict")
        try:
            endpoint = validate_local_ollama_url(spec.endpoint)
        except (ValueError, TypeError, AttributeError):
            raise CodingError(
                "invalid_config",
                "the model endpoint must be an approved local Ollama origin") from None
        self.spec = spec
        self.digest = digest
        self._endpoint = endpoint
        self._transport = transport


    async def verify(self) -> dict[str, Any]:
        """Confirm one substantive local installation of the pinned model.

        Returns the observed name, normalized digest and advertised capabilities.
        The controller calls this before a loop; ``turn`` re-checks the digest.
        """
        async def probe() -> dict[str, Any]:
            async with self._client(VERIFY_TIMEOUT_SECONDS) as client:
                entry = await self._pinned_entry(client)
                body = await self._request(client, "POST", "/api/show",
                                           {"model": self.spec.name})
                _reject_remote(body)
                return {"name": entry["name"], "digest": entry["digest"],
                        "capabilities": _capabilities(body)}

        try:
            return await asyncio.wait_for(probe(), timeout=VERIFY_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            raise CodingError("model_timeout",
                              "local model verification exceeded its deadline") from None

    async def turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                   max_output_tokens: int, timeout_seconds: float,
                   output_schema: dict[str, Any] | None = None) -> ModelReply:
        """Run one bounded native tool-calling turn against the pinned model.

        The deadline covers the whole turn, including the digest checks taken
        before and after the call, so a replaced model fails the turn instead of
        being silently accepted.
        """
        messages = _validate_messages(messages)
        tool_names = _validate_tools(tools)
        if output_schema is not None and (
            not isinstance(output_schema, dict) or output_schema.get("type") != "object" or tools
        ):
            raise CodingError("invalid_request", "structured output requires an object schema and no tools")
        if (type(max_output_tokens) is not int
                or not 1 <= max_output_tokens <= self.spec.output_tokens):
            raise CodingError("invalid_request",
                              "the output token limit is outside the configured budget")
        if (type(timeout_seconds) not in {int, float} or not math.isfinite(timeout_seconds)
                or not 1 <= timeout_seconds <= MAX_TURN_SECONDS):
            raise CodingError("invalid_request", "a turn deadline must be 1 to 600 seconds")
        bound = prompt_bound(messages, tools, output_schema=output_schema)
        if bound + max_output_tokens > self.spec.context_tokens:
            raise CodingError("invalid_request",
                              "the prompt reservation and output limit exceed the model context")
        try:
            return await asyncio.wait_for(
                self._turn(messages, tools, tool_names, bound, max_output_tokens,
                           float(timeout_seconds), output_schema),
                timeout=timeout_seconds)
        except asyncio.TimeoutError:
            raise CodingError("model_timeout",
                              "the local model turn exceeded its deadline") from None

    async def _turn(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                    tool_names: frozenset[str], bound: int, max_output_tokens: int,
                    timeout_seconds: float,
                    output_schema: dict[str, Any] | None = None) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.spec.name, "messages": messages, "stream": False, "think": False,
            "options": {"temperature": 0, "num_ctx": self.spec.context_tokens,
                        "num_predict": max_output_tokens},
        }
        if tools:
            payload["tools"] = tools
        if output_schema is not None:
            payload["format"] = output_schema
        async with self._client(timeout_seconds) as client:
            await self._pinned_entry(client)
            body = await self._request(client, "POST", "/api/chat", payload)
            try:
                reply = self._reply(body, tool_names, bound, max_output_tokens)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise CodingError("provider_contract", "the local model returned invalid content") from None
            await self._pinned_entry(client)
        return reply

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._endpoint, timeout=timeout, trust_env=False,
                                 follow_redirects=False, transport=self._transport)

    async def _request(self, client: httpx.AsyncClient, method: str, path: str,
                       payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bounded request and response; the cap applies before data is buffered."""
        data = bytearray()
        try:
            async with client.stream(method, path, json=payload) as response:
                if response.status_code != 200:
                    status = response.status_code
                    raise CodingError("model_unavailable",
                                      f"the local model endpoint returned HTTP {status}")
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                        raise CodingError("provider_contract",
                                          "the local model response exceeds its size limit")
                    data.extend(chunk)
        except httpx.TimeoutException:
            raise CodingError("model_timeout", "the local model did not answer in time") from None
        except httpx.HTTPError:
            raise CodingError("model_unavailable",
                              "the local model endpoint is unreachable") from None
        try:
            body = strict_json(bytes(data))
        except (ValueError, UnicodeError, RecursionError):
            raise CodingError("provider_contract",
                              "the local model returned unusable JSON") from None
        if not isinstance(body, dict):
            raise CodingError("provider_contract",
                              "the local model returned an unexpected JSON shape")
        return body

    async def _pinned_entry(self, client: httpx.AsyncClient) -> dict[str, str]:
        """Locate the exact configured model and require the pinned local digest."""
        body = await self._request(client, "GET", "/api/tags")
        models = body.get("models")
        if not isinstance(models, list) or len(models) > MAX_CATALOG_ENTRIES:
            raise CodingError("provider_contract", "the local model catalog is unusable")
        for entry in models:
            if not isinstance(entry, dict):
                raise CodingError("provider_contract", "the local model catalog is unusable")
            if self.spec.name != entry.get("name") and self.spec.name != entry.get("model"):
                continue
            _reject_remote(entry)
            size = entry.get("size")
            if type(size) is not int or size < MIN_LOCAL_MODEL_BYTES:
                raise CodingError("model_unavailable",
                                  "the configured model is not a substantive local installation")
            digest = entry.get("digest")
            if not isinstance(digest, str):
                raise CodingError("provider_contract", "the local model catalog omits a digest")
            digest = digest.removeprefix("sha256:").lower()
            if not DIGEST_PATTERN.fullmatch(digest):
                raise CodingError("provider_contract",
                                  "the local model digest is not a SHA-256 digest")
            if digest != self.digest:
                raise CodingError("model_changed",
                                  "the installed model is not the pinned model digest")
            # The name matched exactly, so it is reported as observed.
            return {"name": self.spec.name, "digest": digest}
        raise CodingError("model_unavailable", "the configured model is not installed locally")

    def _reply(self, body: dict[str, Any], tool_names: frozenset[str], bound: int,
               max_output_tokens: int) -> ModelReply:
        if body.get("done") is not True:
            raise CodingError("provider_contract", "the local model did not finish its reply")
        reason = body.get("done_reason")
        if reason is not None and reason not in {"stop", "tool_calls"}:
            raise CodingError("provider_contract", "the local model truncated its reply")
        if body.get("model") != self.spec.name:
            raise CodingError("model_changed", "a different model answered the request")
        message = body.get("message")
        if not isinstance(message, dict) or set(message) - REPLY_FIELDS:
            raise CodingError("provider_contract",
                              "the local model reply has an unexpected message shape")
        if message.get("role") != "assistant":
            raise CodingError("provider_contract", "the local model reply used an unexpected role")
        if message.get("thinking") or message.get("images"):
            raise CodingError("provider_contract",
                              "the local model returned content that was disabled")
        content = message.get("content", "")
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise CodingError("provider_contract",
                              "the local model reply text is invalid or too large")
        calls = _reply_calls(message.get("tool_calls"), tool_names)
        if not content.strip() and not calls:
            raise CodingError("provider_contract", "the local model reply has no usable output")
        used_input = body.get("prompt_eval_count")
        used_output = body.get("eval_count")
        if (type(used_input) is not int or type(used_output) is not int
                or not 0 <= used_input <= bound or not 0 <= used_output <= max_output_tokens):
            raise CodingError("provider_contract",
                              "the local model reported untrustworthy token usage")
        return ModelReply(content, calls, used_input, used_output)


def _reply_calls(value: object, tool_names: frozenset[str]) -> tuple[ToolCall, ...]:
    """Accept only native function calls for tools that were actually offered."""
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_TOOL_CALLS:
        raise CodingError("provider_contract",
                          "the local model requested an unsupported number of tool calls")
    calls = []
    for item in value:
        if (not isinstance(item, dict) or set(item) - {"id", "type", "function"}
                or item.get("type", "function") != "function"):
            raise CodingError("provider_contract", "a tool call has an unexpected shape")
        if "id" in item and (not isinstance(item["id"], str)
                             or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", item["id"])):
            raise CodingError("provider_contract", "a tool call identifier is invalid")
        function = item.get("function")
        if not isinstance(function, dict) or set(function) - {"index", "name", "arguments",
                                                              "description"}:
            raise CodingError("provider_contract", "a tool call has an unexpected shape")
        name = function.get("name")
        if not isinstance(name, str) or name not in tool_names:
            raise CodingError("provider_contract",
                              "the local model requested a tool that was not offered")
        arguments = function.get("arguments", {})
        if not isinstance(arguments, dict):
            raise CodingError("provider_contract",
                              "tool call arguments must be a native JSON object")
        if len(canonical_json(arguments).encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
            raise CodingError("provider_contract",
                              "tool call arguments exceed the per-call limit")
        index = function.get("index", 0)
        if type(index) is not int or not 0 <= index < MAX_TOOL_CALLS:
            raise CodingError("provider_contract", "a tool call index is out of range")
        calls.append(ToolCall(name, arguments))
    return tuple(calls)
