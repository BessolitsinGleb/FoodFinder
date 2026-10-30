from fastapi import APIRouter, Depends
from app.api.deps import rate_limit
from app.api.routes import agent, auth, categories, geo, health, letters, orders, users

api_router = APIRouter()
# health без лимита: его дёргают мониторинг и платформа деплоя
api_router.include_router(health.router)

limited = [Depends(rate_limit)]
api_router.include_router(auth.router, dependencies=limited)
api_router.include_router(geo.router, dependencies=limited)
api_router.include_router(users.router, dependencies=limited)
api_router.include_router(categories.router, dependencies=limited)
api_router.include_router(orders.router, dependencies=limited)
api_router.include_router(letters.router, dependencies=limited)
api_router.include_router(agent.router, dependencies=limited)
