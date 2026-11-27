"""Проверка структурированных ответов локальной Ollama."""

import os

from pydantic import ValidationError


def host():
    value = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    return value if "://" in value else "http://" + value


class InvalidDecision(ValueError):
    """Модель ответила, но не передала структурированный результат."""


async def structured(client, url, *, json, expected, retry_limit=0):
    payload = json
    while True:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        limit = payload["options"]["num_predict"]
        try:
            return expected.model_validate_json(data["message"]["content"])
        except (ValidationError, KeyError, TypeError) as err:
            if data.get("done_reason") == "length" and limit < retry_limit:
                payload = {
                    **payload,
                    "options": {**payload["options"], "num_predict": retry_limit},
                }
                continue
            if data.get("done_reason") == "length":
                raise InvalidDecision(
                    f"Модель исчерпала лимит {limit} токенов до выдачи JSON."
                ) from err
            raise InvalidDecision(
                "Модель вернула ответ, который не соответствует схеме JSON."
            ) from err
