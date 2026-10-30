from fastapi import APIRouter, status
from app.api.deps import CurrentUser, UserServiceDep
from app.models import User
from app.schemas import UserRead, UserUpdate

# Только "я": списка пользователей и чужих профилей в API нет
router = APIRouter(prefix="/users", tags=["users"])

@router.get("/me", response_model=UserRead)
async def get_me(user: CurrentUser) -> User:
    return user

@router.patch("/me", response_model=UserRead)
async def update_me(payload: UserUpdate, user: CurrentUser, service: UserServiceDep) -> User:
    return await service.update(user, payload)

@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(user: CurrentUser, service: UserServiceDep) -> None:
    await service.delete(user)
