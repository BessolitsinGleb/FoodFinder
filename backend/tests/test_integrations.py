"""Клиенты внешних сервисов: разбор ответов и ошибок без реальной сети."""
import asyncio
import json
from types import SimpleNamespace

import httpx2
import pytest

from app.core.config import LLMSettings, WebSearchSettings
from app.core.exceptions import ExternalServiceError
from app.integrations.llm import LLMClient
from app.integrations.web_search import WebSearchClient
from app.schemas.llm import ExtractedSuppliers, ReputationFacts


def _llm_with_replies(*replies):
    llm = LLMClient(LLMSettings(api_key="test"))
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content=replies[len(calls) - 1])
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])

    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return llm, calls


def test_complete_json_strips_code_fence_and_cleans_values():
    reply = '```json\n{"suppliers": [{"name": "Ромашка", "match": "exact", "price": "от 45 000,50 руб.", "phones": null}]}\n```'
    llm, calls = _llm_with_replies(reply)
    result = asyncio.run(llm.complete_json(system="s", user="u", schema=ExtractedSuppliers))

    supplier = result.suppliers[0]
    assert str(supplier.price) == "45000.50"
    assert supplier.phones == []
    assert calls[0]["response_format"] == {"type": "json_object"}
    # Найдено вживую: с reasoning DeepSeek упирался в max_tokens и отдавал пустой ответ
    assert calls[0]["extra_body"] == {"reasoning": {"enabled": False}}
    assert "JSON-схеме" in calls[0]["messages"][0]["content"]


def test_complete_json_retries_then_fails():
    llm, calls = _llm_with_replies("не json", '{"rating": 4.5, "inn": "ИНН 1655 000 000"}')
    facts = asyncio.run(llm.complete_json(system="s", user="u", schema=ReputationFacts))
    assert len(calls) == 2
    assert facts.inn == "1655000000"

    llm, _ = _llm_with_replies("мусор", "опять мусор")
    with pytest.raises(ExternalServiceError):
        asyncio.run(llm.complete_json(system="s", user="u", schema=ReputationFacts))


def _web_with_handler(handler):
    return WebSearchClient(WebSearchSettings(api_key="tvly-test"), transport=httpx2.MockTransport(handler))


def test_web_search_parses_results():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer tvly-test"
        body = json.loads(request.content)
        assert body["query"] == "сухое молоко" and body["max_results"] == 3
        return httpx2.Response(200, json={"results": [{"title": "T", "url": "https://a.ru", "content": None}]})

    results = asyncio.run(_web_with_handler(handler).search("сухое молоко", max_results=3))
    assert results[0].url == "https://a.ru" and results[0].content == ""


def test_web_search_limit_error():
    web = _web_with_handler(lambda request: httpx2.Response(432, json={"detail": "limit"}))
    with pytest.raises(ExternalServiceError, match="лимит"):
        asyncio.run(web.search("x"))


def test_bad_header_values_are_ignored():
    """Найдено в Docker: комментарий из .env попал в LLM__APP_URL, кириллица в заголовке роняла поиск."""
    llm = LLMClient(LLMSettings(api_key="test", app_url="# необязательно: HTTP-Referer", app_title="Поставщики"))
    headers = llm._client.default_headers
    assert "HTTP-Referer" not in headers and "X-Title" not in headers

    llm = LLMClient(LLMSettings(api_key="test", app_url="https://foodfinder.ru", app_title="FoodFinder"))
    assert llm._client.default_headers["HTTP-Referer"] == "https://foodfinder.ru"
    assert llm._client.default_headers["X-Title"] == "FoodFinder"
