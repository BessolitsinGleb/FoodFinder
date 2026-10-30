"""Фейки OpenRouter и Tavily.

Сценарий "интернета":
- Молоко ищем в Казани. Находятся: Агро-Молоко (Казань, свой сайт, цена за тонну),
  МолТорг (Самара, цена за кг), Старый завод (Москва, позже окажется ликвидирован).
- Крафт-пакеты: находится та же Агро-Молоко (тот же домен — один поставщик в двух категориях)
  и ПакетПром (без цены).
"""
import json

from openai.types.chat import ChatCompletion

from app.integrations.web_search import SearchResult
from app.schemas.llm import ExtractedSuppliers, GeneratedLetter, ReputationFacts

MILK_SUPPLIERS = [
    {
        "name": "ООО «Агро-Молоко»", "website": "https://www.agro-moloko.ru/catalog",
        "city": "Казань", "region": "Республика Татарстан", "phones": ["+7 843 000-00-00"],
        "product_name": "Молоко сухое цельное 26%", "match": "exact",
        "price": "450 000", "price_unit": "т", "moq": 500, "moq_unit": "кг",
        "delivery_terms": "Доставка по ПФО", "regions_served": ["ПФО"],
        "certificates": ["Декларация соответствия ТР ТС 033/2013"],
        "source_url": "https://agro-moloko.ru/catalog", "summary": "Производитель, рядом",
    },
    {
        "name": "МолТорг", "website": "moltorg.ru", "city": "Самара", "region": "Самарская обл.",
        "emails": ["sales@moltorg.ru"], "match": "exact", "price": 400, "price_unit": "руб/кг",
        "regions_served": ["вся Россия"], "source_url": "https://moltorg.ru",
        "delivery_time": "2-3 рабочих дня",
    },
    {
        "name": "Старый завод", "website": "https://moscow.pulscen.ru/firm/123", "city": "Москва",
        "match": "partial", "source_url": "https://moscow.pulscen.ru/firm/123",
    },
    {"name": "Левый товар", "match": "none"},
]

PACKAGING_SUPPLIERS = [
    {
        "name": "Агро-Молоко", "website": "agro-moloko.ru", "city": "Казань",
        "region": "Татарстан", "match": "partial", "source_url": "https://agro-moloko.ru/pack",
    },
    {
        "name": "ПакетПром", "website": "paketprom.ru", "city": "Казань", "region": "Татарстан",
        "match": "exact", "phones": ["+7 843 111-11-11"], "source_url": "https://paketprom.ru",
    },
]

REPUTATION = {
    "Агро-Молоко": {
        "inn": "1655000000", "founded_year": 2010, "rating": 4.7, "reviews_count": 150,
        "certificates": ["ISO 22000"],
    },
    "МолТорг": {"rating": 4.0, "reviews_count": 5},
    "Старый завод": {"is_liquidated": True, "red_flags": ["Ликвидирована в 2024"]},
}


class FakeWebSearch:
    def __init__(self):
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        self.queries.append(query)
        if "отзывы" in query or "ИНН" in query:
            # В тексте результата есть название компании — так считается "упоминание"
            name = query.split(" отзывы")[0].split(" ИНН")[0]
            slug = abs(hash(query)) % 1000
            return [SearchResult(f"{name}: отзывы", f"https://reviews{slug}.ru/{slug}", f"Про {name}")]
        return [SearchResult("Каталог", f"https://catalog.ru/{len(self.queries)}", "Список поставщиков")]

    async def close(self):
        pass


class FakeLLM:
    def __init__(self):
        self.prompts: list[str] = []
        self.chat_script: list = []
        self.chat_calls: list[list[dict]] = []
        self.chat_tools: list[set[str]] = []
        self.on_call = None  # хук для тестов: вызывается в момент "запроса к модели"

    async def complete_json(self, *, system: str, user: str, schema, attempts: int = 2):
        self.prompts.append(user)
        if self.on_call:
            self.on_call()
        if schema is ExtractedSuppliers:
            suppliers = PACKAGING_SUPPLIERS if "Крафт" in user else MILK_SUPPLIERS
            return ExtractedSuppliers.model_validate({"suppliers": suppliers})
        if schema is ReputationFacts:
            for name, facts in REPUTATION.items():
                if name in user:
                    return ReputationFacts.model_validate(facts)
            return ReputationFacts()
        if schema is GeneratedLetter:
            name = user.split("Поставщик: ")[1].split("\n")[0]
            # Без подписи: сервис должен добавить её сам
            return GeneratedLetter(subject=f"Запрос КП для {name}", body=f"Добрый день, {name}!\n{user}")
        raise AssertionError(f"Неожиданная схема {schema}")

    async def chat(self, messages, tools=None, **kwargs):
        """Отвечает репликами из chat_script по очереди, по умолчанию — "Готово".

        Реплика — либо строка (финальный ответ), либо список вызовов тулов [(name, args), ...].
        """
        self.chat_calls.append([dict(m) for m in messages])
        if self.on_call:
            self.on_call()
        self.chat_tools.append({t["function"]["name"] for t in tools or []})
        step = self.chat_script.pop(0) if self.chat_script else "Готово"
        if isinstance(step, str):
            message = {"role": "assistant", "content": step}
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": f"call_{i}", "type": "function",
                     "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
                    for i, (name, args) in enumerate(step)
                ],
            }
        return ChatCompletion.model_validate({
            "id": "fake", "object": "chat.completion", "created": 0, "model": "fake-model",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        })

    async def close(self):
        pass


class FakeMailer:
    """Вместо SMTP: запоминает последний код для каждого адреса."""

    def __init__(self):
        self.codes: dict[str, str] = {}
        self.fail = False

    async def send_verification_code(self, email: str, code: str) -> None:
        if self.fail:
            from app.core.exceptions import ExternalServiceError
            raise ExternalServiceError("Не удалось отправить письмо с кодом, попробуйте позже")
        self.codes[email] = code
