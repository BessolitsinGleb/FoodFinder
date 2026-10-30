"""Ограничитель частоты запросов на Redis: скользящее окно.

В sorted set по ключу клиента лежат отметки времени его запросов. Lua-скрипт
выполняется в Redis атомарно, поэтому два параллельных запроса не "проскочат"
лимит одновременно.
"""
import logging
import time
import uuid
from redis.asyncio import Redis
from redis.exceptions import RedisError
from app.core.config import RateLimitSettings

logger = logging.getLogger(__name__)

SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
if redis.call('ZCARD', key) >= limit then
    return 0
end
redis.call('ZADD', key, now, member)
redis.call('PEXPIRE', key, window)
return 1
"""

class RateLimiter:
    def __init__(self, redis: Redis, settings: RateLimitSettings) -> None:
        self.settings = settings
        self._script = redis.register_script(SLIDING_WINDOW_LUA)

    async def allow(self, client_key: str) -> bool:
        now_ms = int(time.time() * 1000)
        try:
            allowed = await self._script(
                keys=[f"rate_limit:{client_key}"],
                # uuid в member: два запроса в одну миллисекунду — это два разных запроса
                args=[now_ms, self.settings.window_ms, self.settings.requests, f"{now_ms}:{uuid.uuid4().hex}"],
            )
        except RedisError as exc:
            # Redis лёг — лучше пропустить запрос, чем положить весь сервис
            logger.warning("Rate limiter unavailable: %s", exc)
            return True
        return bool(allowed)
