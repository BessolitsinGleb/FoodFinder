from urllib.parse import quote
from fastapi import APIRouter, status
from fastapi.responses import PlainTextResponse
from app.api.deps import CurrentUser, LetterServiceDep
from app.models import Letter
from app.schemas import LetterCreate, LetterRead

router = APIRouter(tags=["letters"])

@router.get("/letters/templates", response_model=list[str])
async def list_templates(user: CurrentUser, service: LetterServiceDep) -> list[str]:
    return service.list_templates()

@router.post(
    "/orders/{order_id}/letters", response_model=list[LetterRead], status_code=status.HTTP_201_CREATED
)
async def generate_letters(
    order_id: int, payload: LetterCreate, user: CurrentUser, service: LetterServiceDep
) -> list[Letter]:
    """По одному письму на каждого поставщика из выбранных предложений."""
    return await service.generate(order_id, user, payload)

@router.get("/orders/{order_id}/letters", response_model=list[LetterRead])
async def list_letters(order_id: int, user: CurrentUser, service: LetterServiceDep) -> list[Letter]:
    return await service.list_for_order(order_id, user)

@router.get("/letters/{letter_id}", response_model=LetterRead)
async def get_letter(letter_id: int, user: CurrentUser, service: LetterServiceDep) -> Letter:
    return await service.get(letter_id, user)

@router.get("/letters/{letter_id}/download", response_class=PlainTextResponse)
async def download_letter(letter_id: int, user: CurrentUser, service: LetterServiceDep) -> PlainTextResponse:
    letter = await service.get(letter_id, user)
    filename = quote(f"zapros-kp-{letter.id}.txt")
    return PlainTextResponse(
        service.render_txt(letter),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )
