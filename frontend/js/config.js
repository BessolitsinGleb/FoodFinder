// Адрес API. Локально бэкенд крутится на :8000.
// На проде задайте window.FF_API_BASE в env.js (см. README) — менять код не нужно.
export const API_BASE = window.FF_API_BASE || "http://localhost:8000/api/v1";

export const APP_NAME = "FoodFinder";

// Бэкенд пускает не больше 3 запросов в секунду — держим запас
export const REQUEST_INTERVAL_MS = 360;

// Как часто проверять прогресс поиска
export const SEARCH_POLL_MS = 3000;
