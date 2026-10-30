"""Клиент LLM (OpenRouter, OpenAI-совместимый API).

Два режима:
- chat() — "сырой" ответ модели, нужен агенту с тулами;
- complete_json() — ответ строго по pydantic-схеме, нужен пайплайну
  (извлечь поставщиков из страниц, оценить репутацию, написать письмо).
"""

import json
import logging
import re
from typing import Any

from openai import APIError, AsyncOpenAI
from openai.types.chat import ChatCompletion
from pydantic import BaseModel, ValidationError

from app.core.config import LLMSettings
from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

# Модель иногда оборачивает JSON в ```json ... ``` — снимаем обёртку
_CODE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LLMClient:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings
        headers: dict[str, str] = {}
        # Необязательные заголовки OpenRouter: показывают приложение в их статистике.
        # Заголовки HTTP — только ASCII. Кривое значение из .env (например, комментарий,
        # который Docker Compose принял за значение) не должно ронять все запросы к LLM.
        app_url = (settings.app_url or "").strip()
        if app_url.startswith(("http://", "https://")) and app_url.isascii():
            headers["HTTP-Referer"] = app_url
        elif app_url:
            logger.warning("LLM__APP_URL ignored: not an ASCII http(s) URL")
        app_title = (settings.app_title or "").strip()
        if app_title.isascii() and app_title:
            headers["X-Title"] = app_title
        elif app_title:
            logger.warning("LLM__APP_TITLE ignored: HTTP headers must be ASCII")

        self._client = AsyncOpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
            default_headers=headers,
        )

    async def close(self) -> None:
        await self._client.close()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        reasoning: bool | None = None,
        **kwargs: Any,
    ) -> ChatCompletion:
        # Пустой список tools некоторые провайдеры не принимают — передаём только если есть
        if tools:
            kwargs["tools"] = tools
        use_reasoning = self.settings.chat_reasoning if reasoning is None else reasoning
        if not use_reasoning:
            # Параметр OpenRouter: без "размышлений" ответ в разы быстрее и дешевле
            kwargs["extra_body"] = {"reasoning": {"enabled": False}}
        try:
            response = await self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                temperature=self.settings.temperature if temperature is None else temperature,
                max_tokens=self.settings.max_tokens,
                **kwargs,
            )
        except APIError as exc:
            logger.warning("LLM request failed: %s", exc)
            raise ExternalServiceError("Ошибка запроса к LLM-провайдеру") from exc

        if not response.choices:
            raise ExternalServiceError("LLM-провайдер вернул пустой ответ")
        return response

    async def complete_json[T: BaseModel](
        self, *, system: str, user: str, schema: type[T], attempts: int = 2
    ) -> T:
        """Получить ответ, провалидированный схемой. При мусоре в ответе пробуем ещё раз."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": f"{system}\n\nОтвечай только JSON-объектом по этой JSON-схеме:\n{schema_json}",
            },
            {"role": "user", "content": user},
        ]

        for attempt in range(1, attempts + 1):
            # Reasoning для извлечения фактов не нужен: проверено вживую, DeepSeek тратил на него
            # 4-5 тыс. токенов, упирался в max_tokens и возвращал пустой ответ (finish_reason=length)
            response = await self.chat(
                messages,
                temperature=0,
                reasoning=self.settings.json_reasoning,
                response_format={"type": "json_object"},
            )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                logger.warning("LLM answer cut by max_tokens (attempt %s)", attempt)
            raw = choice.message.content or ""
            try:
                return schema.model_validate_json(_CODE_FENCE.sub("", raw.strip()))
            except ValidationError as exc:
                logger.warning("LLM returned invalid JSON (attempt %s): %s", attempt, exc)

        raise ExternalServiceError("LLM вернул ответ не по формату")
