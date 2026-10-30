import re
from itertools import groupby

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import LettersSettings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.integrations.llm import LLMClient
from app.models import Letter, Order, OrderStatus, User
from app.prompts.letters import LETTER_SYSTEM, SIGNATURE, letter_prompt
from app.repositories.letter_repo import LetterRepo
from app.repositories.order_repo import OrderRepo
from app.repositories.supplier_repo import OfferRepo
from app.schemas import LetterCreate
from app.schemas.llm import GeneratedLetter
from app.services.base import BaseService

_TEMPLATE_NAME = re.compile(r"^[\w-]+$")


class LetterService(BaseService):
    """Письма-запросы КП: одно письмо на поставщика по всем выбранным у него позициям."""

    def __init__(self, session: AsyncSession, llm: LLMClient | None, settings: LettersSettings) -> None:
        super().__init__(session)
        self.order_repo = OrderRepo(session)
        self.offer_repo = OfferRepo(session)
        self.letter_repo = LetterRepo(session)
        self.llm = llm
        self.settings = settings

    def list_templates(self) -> list[str]:
        return sorted(path.stem for path in self.settings.templates_dir.glob("*.txt"))

    def _load_template(self, name: str) -> str:
        # Имя приходит от пользователя: только буквы/цифры/дефис, никаких "../"
        path = self.settings.templates_dir / f"{name}.txt"
        if not _TEMPLATE_NAME.match(name) or not path.is_file():
            raise NotFoundError(f"Шаблон '{name}' не найден. Доступные: {', '.join(self.list_templates())}")
        return path.read_text(encoding="utf-8")

    async def _get_order(self, order_id: int, user: User) -> Order:
        order = await self.order_repo.get(order_id)
        if order is None or order.user_id != user.id:
            raise NotFoundError(f"Заказ {order_id} не найден")
        return order

    async def generate(self, order_id: int, user: User, data: LetterCreate) -> list[Letter]:
        if self.llm is None:
            raise ServiceUnavailableError("LLM не настроен: задайте LLM__API_KEY")
        order = await self._get_order(order_id, user)
        if order.status not in (OrderStatus.READY, OrderStatus.COMPLETED):
            raise ConflictError("Письма формируются после поиска поставщиков")

        offers = await self.offer_repo.list_by_ids(order_id, data.offer_ids)
        missing = set(data.offer_ids) - {offer.id for offer in offers}
        if missing:
            raise NotFoundError(f"Предложения {sorted(missing)} не найдены в заказе {order_id}")

        template_name = data.template or self.settings.default_template
        template = self._load_template(template_name)
        # Данные загружены — отпускаем подключение на время генерации (по вызову LLM на поставщика)
        await self.session.commit()

        letters = []
        # offers отсортированы по поставщику: группа = все позиции одного поставщика
        for supplier_id, group in groupby(offers, key=lambda offer: offer.supplier_id):
            group = list(group)
            supplier = group[0].supplier
            generated = await self.llm.complete_json(
                system=LETTER_SYSTEM,
                user=letter_prompt(
                    template,
                    supplier,
                    [offer.order_item for offer in group],
                    order.delivery_city,
                    order.delivery_region,
                ),
                schema=GeneratedLetter,
            )
            letter = Letter(
                order_id=order.id,
                supplier_id=supplier_id,
                template=template_name,
                subject=generated.subject.strip()[:300],
                body=_ensure_signature(generated.body.strip()),
            )
            self.letter_repo.add(letter)
            letters.append(letter)
            for offer in group:
                offer.is_selected = True

        order.status = OrderStatus.COMPLETED
        await self.session.commit()
        return letters

    async def list_for_order(self, order_id: int, user: User) -> list[Letter]:
        await self._get_order(order_id, user)
        return list(await self.letter_repo.list_for_order(order_id))

    async def get(self, letter_id: int, user: User) -> Letter:
        letter = await self.letter_repo.get_for_user(letter_id, user.id)
        if letter is None:
            raise NotFoundError(f"Письмо {letter_id} не найдено")
        return letter

    @staticmethod
    def render_txt(letter: Letter) -> str:
        return f"Тема: {letter.subject}\n\n{letter.body}\n"


def _ensure_signature(body: str) -> str:
    """Если модель потеряла подпись с полями для личных данных — добавляем её сами."""
    return body if "[ФИО]" in body else f"{body}\n\n{SIGNATURE}"
