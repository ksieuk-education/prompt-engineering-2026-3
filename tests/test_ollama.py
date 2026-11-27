import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from studio.ollama import InvalidDecision, structured


class Answer(BaseModel):
    ok: bool


def test_retry_uses_one_larger_budget_only_after_a_truncated_response():
    seen = []

    def respond(request):
        seen.append(json.loads(request.content)["options"]["num_predict"])
        full = len(seen) > 1
        return httpx.Response(
            200,
            json={
                "done_reason": "stop" if full else "length",
                "message": {"content": '{"ok":true}' if full else ""},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await structured(
                client,
                "http://model/chat",
                json={"options": {"num_predict": 50}},
                expected=Answer,
                retry_limit=500,
            )

    assert asyncio.run(run()).ok and seen == [50, 500]


def test_invalid_complete_output_reports_a_format_problem_immediately():
    def respond(request):
        return httpx.Response(
            200, json={"done_reason": "stop", "message": {"content": "{}"}}
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await structured(
                client,
                "http://model/chat",
                json={"options": {"num_predict": 50}},
                expected=Answer,
                retry_limit=500,
            )

    with pytest.raises(InvalidDecision, match="не соответствует"):
        asyncio.run(run())
