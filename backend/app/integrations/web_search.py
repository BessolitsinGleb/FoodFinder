"""Поиск в интернете через Tavily (https://docs.tavily.com).

Tavily сразу отдаёт очищенный текст страниц (content), поэтому не нужно
самим скачивать и парсить HTML — достаточно передать результаты в LLM.
"""

import logging
from dataclasses import dataclass

import httpx2

from app.core.config import WebSearchSettings
from app.core.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

# 429 — rate limit, 432/433 — исчерпан лимит тарифа
_LIMIT_STATUSES = {429, 432, 433}


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    content: str


class WebSearchClient:
    def __init__(
        self, settings: WebSearchSettings, transport: httpx2.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        # transport подменяется в тестах (MockTransport), в проде — обычная сеть
        self._http = httpx2.AsyncClient(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key.get_secret_value()}"},
            timeout=settings.timeout,
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        payload = {
            "query": query,
            "search_depth": self.settings.search_depth,
            "max_results": max_results,
            "topic": "general",
            # Поднимает в выдаче российские сайты (работает только с topic=general)
            "country": "russia",
        }
        try:
            response = await self._http.post("/search", json=payload)
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            logger.warning("Tavily error %s: %s", exc.response.status_code, exc.response.text[:300])
            if exc.response.status_code in _LIMIT_STATUSES:
                raise ExternalServiceError("Исчерпан лимит запросов к поиску (Tavily)") from exc
            raise ExternalServiceError("Ошибка поискового сервиса") from exc
        except httpx2.HTTPError as exc:
            logger.warning("Tavily request failed: %s", exc)
            raise ExternalServiceError("Поисковый сервис недоступен") from exc

        logger.info("Web search: %r", query)
        return [
            SearchResult(title=r.get("title") or "", url=r["url"], content=r.get("content") or "")
            for r in response.json().get("results", [])
        ]
