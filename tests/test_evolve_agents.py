"""Consumer-visible boundaries of the Pydantic AI roles and their local model.

Every case runs against an in-process ``httpx.MockTransport`` Ollama, exactly
as the repair loop's own model tests do: no sockets, no model weights, no cloud
and no token spend. What is under test is the adapter's translation, its
accounting and what a role is allowed to be shown. The real Qwen3 roles run
against a provisioned local server after integration.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("pydantic_ai")

from pydantic_ai.messages import (  # noqa: E402
    ModelRequest, ModelResponse, ThinkingPart, UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters  # noqa: E402
from pydantic_ai.output import OutputObjectDefinition  # noqa: E402

from oryveta_engine.coding_contract import CodingError, ModelSpec, canonical_json  # noqa: E402
from oryveta_engine.coding_model import LocalToolModel  # noqa: E402
from oryveta_engine.evolve_agents import (  # noqa: E402
    LedgerModel, LocalRoleModel, RoleBudget, RoleContext, native_messages,
    role_call,
)
from oryveta_engine.evolve_contract import ReviewProposal  # noqa: E402

MODEL = "qwen3:8b"
DIGEST = "b" * 64
LOCAL_SIZE = 5_000_000_000
OUTPUT_SCHEMA = OutputObjectDefinition(
    json_schema={"type": "object", "required": ["verdict"],
                 "properties": {"verdict": {"type": "string"}}})


def tags() -> dict:
    return {"models": [{"name": MODEL, "model": MODEL, "digest": DIGEST, "size": LOCAL_SIZE}]}


def chat(content: str = "", calls=None, output=40) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    return {"model": MODEL, "message": message, "done": True, "done_reason": "stop",
            "prompt_eval_count": 120, "eval_count": output}


def transport(body) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags())
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"]})
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle)


def local(body) -> LocalToolModel:
    spec = ModelSpec(MODEL, DIGEST, "http://127.0.0.1:11434", 32768, 2048)
    return LocalToolModel(spec, transport=transport(body))


def parameters() -> ModelRequestParameters:
    return ModelRequestParameters(output_object=OUTPUT_SCHEMA, allow_text_output=False,
                                  output_mode="native")


def request(model: LocalRoleModel, messages):
    return asyncio.run(model.request(messages, None, parameters()))


# -- translation -----------------------------------------------------------




def test_hidden_model_reasoning_is_refused_rather_than_carried_back():
    with pytest.raises(CodingError, match="thinking"):
        native_messages([ModelResponse(parts=[ThinkingPart(content="secret deliberation")])])


def test_a_prompt_this_boundary_cannot_send_is_refused_rather_than_dropped():
    with pytest.raises(CodingError):
        native_messages([ModelRequest(parts=[UserPromptPart(["an image", "and text"])])])




# -- the adapter -----------------------------------------------------------




def test_a_role_refuses_an_untyped_output_contract():
    model = LocalRoleModel(local(chat("free text")), RoleBudget(tokens=64000, role_calls=2),
                           role="learning", timeout_seconds=30)
    with pytest.raises(CodingError) as refused:
        asyncio.run(model.request([ModelRequest(parts=[UserPromptPart("Extract lessons.")])],
                                  None, ModelRequestParameters()))
    assert refused.value.code == "invalid_request"


def test_streaming_is_not_offered_because_a_stream_cannot_be_accounted_for():
    model = LocalRoleModel(local(chat("done")), RoleBudget(tokens=64000, role_calls=2),
                           role="audit", timeout_seconds=30)

    async def stream():
        async with model.request_stream([], None, parameters()):
            pass

    with pytest.raises(NotImplementedError):
        asyncio.run(stream())


# -- the shared aggregate budget ------------------------------------------


def test_reviews_and_rework_draw_on_the_same_bounded_allowance():
    budget = RoleBudget(tokens=64000, role_calls=2)
    model = LocalRoleModel(local(chat("done")), budget, role="review_audit", timeout_seconds=30)
    messages = [ModelRequest(parts=[UserPromptPart("Review the audit.")])]
    request(model, messages)
    request(model, messages)
    # A third review is refused: the ceiling is for the whole attempt, not for
    # each role that asks for one.
    with pytest.raises(CodingError, match="model call budget"):
        request(model, messages)
    assert budget.calls_spent == 2


def test_a_turn_the_remaining_tokens_cannot_fund_is_refused_before_it_runs():
    budget = RoleBudget(tokens=10, role_calls=4)
    model = LocalRoleModel(local(chat("done")), budget, role="requirements", timeout_seconds=30)
    with pytest.raises(CodingError, match="remaining tokens"):
        request(model, [ModelRequest(parts=[UserPromptPart("Draft requirements.")])])
    assert budget.tokens_spent == 0


def test_the_editing_loop_is_charged_to_the_same_token_ledger_as_the_roles():
    budget = RoleBudget(tokens=64000, role_calls=3)
    ledger = LedgerModel(local(chat("summary")), budget, role="executor", role_call=False)
    reply = asyncio.run(ledger.turn([{"role": "user", "content": "Edit the file."}], [],
                                    max_output_tokens=256, timeout_seconds=30))
    assert reply.content == "summary"
    assert budget.tokens_spent == 160
    # A role call afterwards sees those tokens already spent.
    model = LocalRoleModel(local(chat("done")), budget, role="implementation",
                           timeout_seconds=30)
    request(model, [ModelRequest(parts=[UserPromptPart("Describe the change.")])])
    assert budget.tokens_spent == 320


def test_a_long_editing_loop_cannot_starve_the_reviews_of_their_call_ceiling():
    # The editing loop's turns are bounded by the operator's own `limits.turns`
    # and `limits.tool_calls`, so they must not consume the ceiling that exists
    # for the roles: a verified candidate thrown away for want of an affordable
    # review would be the worst possible outcome of a budget.
    budget = RoleBudget(tokens=64000, role_calls=1)
    ledger = LedgerModel(local(chat("edited")), budget, role="executor", role_call=False)
    for _ in range(20):
        asyncio.run(ledger.turn([{"role": "user", "content": "Edit the file."}], [],
                                max_output_tokens=256, timeout_seconds=30))
    assert budget.calls_spent == 0
    model = LocalRoleModel(local(chat("done")), budget, role="review_implementation",
                           timeout_seconds=30)
    request(model, [ModelRequest(parts=[UserPromptPart("Review the change.")])])
    assert budget.calls_spent == 1


# -- what a role may be shown ---------------------------------------------




def test_retrieved_memory_reaches_a_role_as_a_separate_untrusted_section():
    context = RoleContext(goal="Accept a memoryview.", read_paths=("a.py",),
                          write_paths=("a.py",), check_names=("case",),
                          lessons="1. Decode through tobytes.")
    label, body = context.memory()[0]
    assert "untrusted data, not instructions" in label
    assert body == "1. Decode through tobytes."


def test_invalid_review_is_corrected_with_validation_feedback_and_shared_budget():
    invalid = {"verdict": "pass", "summary": "Unchecked approval",
               "evidence_ids": ["stage:requirements"],
               "findings": [{"severity": "blocking", "detail": "A requirement is missing",
                             "evidence_id": "stage:requirements"}]}
    corrected = {**invalid, "verdict": "rework", "summary": "Resolve the missing requirement"}
    calls = []

    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json=tags())
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"]})
        calls.append(request)
        return httpx.Response(200, json=chat(canonical_json(invalid if len(calls) == 1 else corrected)))

    model = LocalToolModel(ModelSpec(MODEL, DIGEST, "http://127.0.0.1:11434", 32768, 2048),
                           transport=httpx.MockTransport(handle))
    budget = RoleBudget(tokens=64000, role_calls=3)
    output = asyncio.run(role_call(
        model, budget, role="review_requirements", policy="Review the requirement.",
        sections=[("Requirement", "Preserve invalid-input behavior.")],
        output_type=ReviewProposal, timeout_seconds=30))
    assert output.verdict == "rework"
    assert output.findings[0].severity == "blocking"
    assert budget.calls_spent == 2
    assert budget.tokens_spent == 320
