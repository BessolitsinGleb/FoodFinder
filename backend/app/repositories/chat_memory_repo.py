"""Последние сообщения диалога с агентом — только в Redis.

Нигде больше не храним: TTL обновляется с каждым сообщением, и после
ChatSettings.history_ttl_seconds тишины история стирается сама.
"""
import json
from redis.asyncio import Redis
from redis.exceptions import RedisError
from app.core.config import ChatSettings
from app.core.exceptions import ServiceUnavailableError

class ChatMemoryRepo:
    def __init__(self, redis: Redis, settings: ChatSettings) -> None:
        self.redis = redis
        self.settings = settings

    @staticmethod
    def _key(user_id: int) -> str:
        return f"chat:{user_id}"

    async def get(self, user_id: int) -> list[dict[str, str]]:
        try:
            raw = await self.redis.lrange(self._key(user_id), 0, -1)
        except RedisError as exc:
            raise ServiceUnavailableError("Хранилище диалогов недоступно") from exc
        return [json.loads(item) for item in raw]

    async def append(self, user_id: int, *messages: dict[str, str]) -> None:
        key = self._key(user_id)
        try:
            # Транзакция: добавить, обрезать до последних N, продлить TTL — одним махом
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.rpush(key, *(json.dumps(m, ensure_ascii=False) for m in messages))
                pipe.ltrim(key, -self.settings.history_messages, -1)
                pipe.expire(key, self.settings.history_ttl_seconds)
                await pipe.execute()
        except RedisError as exc:
            raise ServiceUnavailableError("Хранилище диалогов недоступно") from exc

    async def clear(self, user_id: int) -> None:
        try:
            await self.redis.delete(self._key(user_id))
        except RedisError as exc:
            raise ServiceUnavailableError("Хранилище диалогов недоступно") from exc
