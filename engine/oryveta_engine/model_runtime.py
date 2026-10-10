"""Provider-neutral, text-only model boundary. No tools or code execution.

The only concrete backend is an explicitly configured local Ollama endpoint.
User input never selects a URL, model, tool, or execution permission.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

MAX_PROMPT_BYTES = 4096
MAX_OUTPUT_TOKENS = 512
MODEL_TIMEOUT_SECONDS = 75
MODEL_STATUS_TIMEOUT_SECONDS = 4
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024


class ProviderContractError(ValueError):
    """The model provider violated a bounded output or usage contract."""


@dataclass(frozen=True)
class ModelCompletion:
    text: str
    prompt_tokens: int
    output_tokens: int
    model: str


class ModelProvider(Protocol):
    async def complete(self, prompt: str, *, max_output_tokens: int,
                       temperature: float) -> ModelCompletion: ...


def prompt_token_ceiling(prompt: str) -> int:
    """Conservative admission estimate, not an exact tokenizer measurement.

    A UTF-8 byte-per-token bound plus a framing allowance is intentionally
    pessimistic for common tokenizers; provider-reported usage is still checked.
    """
    size = len(prompt.encode("utf-8"))
    if not size or size > MAX_PROMPT_BYTES:
        raise ValueError("Prompt must contain 1 to 4096 UTF-8 bytes")
    return size + 128


def validate_local_ollama_url(base_url: str) -> str:
    url = urlsplit(base_url)
    if (url.scheme != "http" or url.hostname not in
            {"127.0.0.1", "localhost", "::1", "ollama"} or
            url.port != 11434 or url.username or url.password or
            url.path not in {"", "/"} or url.query or url.fragment):
        raise ValueError("Ollama must use an approved local endpoint on port 11434")
    return base_url.rstrip("/")


class OllamaProvider:
    """Open-weight local inference with no arbitrary URL or tool execution."""

    def __init__(self, base_url: str, model: str):
        self.base_url = validate_local_ollama_url(base_url)
        if not model or len(model) > 100 or any(c not in
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for c in model):
            raise ValueError("Invalid configured Ollama model identifier")
        self.model = model

    async def status(self) -> dict[str, str]:
        """Bounded, non-secret model readiness probe. No generation or token spend."""
        async def probe():
            async with httpx.AsyncClient(timeout=MODEL_STATUS_TIMEOUT_SECONDS,
                                         trust_env=False, follow_redirects=False) as client:
                async with client.stream("GET", f"{self.base_url}/api/tags") as response:
                    response.raise_for_status()
                    body = await read_bounded_json(response)
            if not isinstance(body, dict) or not isinstance(body.get("models"), list):
                raise ProviderContractError("Invalid Ollama model catalog")
            names = [item.get("name") for item in body["models"]
                     if isinstance(item, dict) and isinstance(item.get("name"), str)]
            return {"status": "ready" if self.model in names else "model_missing",
                    "model": self.model}
        try:
            return await asyncio.wait_for(probe(), timeout=MODEL_STATUS_TIMEOUT_SECONDS)
        except (httpx.HTTPError, ValueError, asyncio.TimeoutError, ProviderContractError):
            return {"status": "offline", "model": self.model}

    async def complete(self, prompt: str, *, max_output_tokens: int = 256,
                       temperature: float = 0.2) -> ModelCompletion:
        ceiling = prompt_token_ceiling(prompt)
        if not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("Output token limit is out of range")
        if not 0 <= temperature <= 1:
            raise ValueError("Temperature is out of range")
        # asyncio.wait_for bounds total time, including a peer that trickles
        # bytes to defeat a socket read timeout. No environment proxy is used.
        async def call():
            async with httpx.AsyncClient(timeout=MODEL_TIMEOUT_SECONDS,
                                         trust_env=False, follow_redirects=False) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False,
                          "options": {"num_predict": max_output_tokens,
                                      "temperature": temperature}},
                ) as response:
                    response.raise_for_status()
                    return await read_bounded_json(response)

        payload = await asyncio.wait_for(call(), timeout=MODEL_TIMEOUT_SECONDS)
        if not isinstance(payload, dict) or payload.get("done") is not True:
            raise ProviderContractError("Provider did not finish a valid response")
        text = payload.get("response")
        used_prompt = payload.get("prompt_eval_count")
        used_output = payload.get("eval_count")
        if (not isinstance(text, str) or len(text.encode("utf-8")) > 16384 or
                type(used_prompt) is not int or type(used_output) is not int or
                not 0 <= used_prompt <= ceiling or
                not 0 <= used_output <= max_output_tokens):
            raise ProviderContractError("Provider exceeded usage or output bounds")
        if payload.get("model") != self.model:
            raise ProviderContractError("Provider returned an unexpected model")
        return ModelCompletion(text, used_prompt, used_output, self.model)


async def read_bounded_json(response: httpx.Response) -> object:
    """Enforce the response cap while streaming, before untrusted data is buffered."""
    data = bytearray()
    async for chunk in response.aiter_bytes():
        if len(data) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderContractError("Provider response exceeds size limit")
        data.extend(chunk)
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProviderContractError("Provider returned invalid JSON") from exc
