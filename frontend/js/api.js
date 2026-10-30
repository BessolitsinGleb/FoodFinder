// Клиент API. Все запросы идут через одну очередь с интервалом REQUEST_INTERVAL_MS:
// бэкенд пускает не больше 3 запросов в секунду, и так страница не упирается в лимит,
// даже если при загрузке ей нужно несколько запросов.
import { API_BASE, REQUEST_INTERVAL_MS } from "./config.js";
import { sleep } from "./utils.js";

const TOKEN_KEY = "ff_token";
const PROFILE_KEY = "ff_profile";

export const session = {
  get token() {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token) {
    localStorage.setItem(TOKEN_KEY, token);
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(PROFILE_KEY);
  },
  get profile() {
    try {
      return JSON.parse(localStorage.getItem(PROFILE_KEY));
    } catch {
      return null;
    }
  },
  set profile(user) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(user));
  },
};

export class ApiError extends Error {
  constructor(status, message, fields = {}) {
    super(message);
    this.status = status;
    this.fields = fields; // ошибки по полям формы: { password: "минимум 8 символов" }
  }
}

// ---------- Очередь запросов ----------

let lastRequestAt = 0;
let queue = Promise.resolve();

function nextSlot() {
  queue = queue.then(async () => {
    const wait = lastRequestAt + REQUEST_INTERVAL_MS - Date.now();
    if (wait > 0) await sleep(wait);
    lastRequestAt = Date.now();
  });
  return queue;
}

// ---------- Разбор ошибок ----------

const FIELD_LABELS = {
  email: "Email", password: "Пароль", name: "Имя", city: "Город", region: "Регион", code: "Код",
  custom_title: "Название", category_id: "Категория", quantity: "Объём", unit: "Единица",
  details: "Требования", address: "Адрес", message: "Сообщение", top_k: "Количество поставщиков",
  user_note: "Заметка", offer_ids: "Поставщики",
};

function validationMessage(error) {
  const ctx = error.ctx || {};
  switch (error.type) {
    case "missing": return "обязательное поле";
    case "string_too_short": return ctx.min_length > 1 ? `минимум ${ctx.min_length} символов` : "заполните поле";
    case "string_too_long": return `максимум ${ctx.max_length} символов`;
    case "greater_than": return `должно быть больше ${ctx.gt}`;
    case "greater_than_equal": return `не меньше ${ctx.ge}`;
    case "less_than_equal": return `не больше ${ctx.le}`;
    case "decimal_parsing":
    case "float_parsing":
    case "int_parsing": return "нужно число";
    case "decimal_max_digits": return "слишком большое число";
    case "decimal_max_places": return "слишком много знаков после запятой";
    case "string_pattern_mismatch": return "неверный формат";
    case "extra_forbidden": return "лишнее поле";
    case "value_error": return (error.msg || "").replace(/^Value error,\s*/, "").replace(/^value is not a valid email address:.*/, "некорректный email");
    default: return error.msg || "некорректное значение";
  }
}

async function parseError(response) {
  let detail = null;
  try {
    detail = (await response.json()).detail;
  } catch {
    // не JSON — например, упал прокси
  }
  if (Array.isArray(detail)) {
    const fields = {};
    const lines = detail.map((e) => {
      const field = [...(e.loc || [])].reverse().find((part) => typeof part === "string" && part !== "body");
      const message = validationMessage(e);
      if (field) fields[field] = message;
      return field && FIELD_LABELS[field] ? `${FIELD_LABELS[field]}: ${message}` : message;
    });
    return new ApiError(response.status, lines.join("; "), fields);
  }
  const fallback = {
    401: "Нужно войти заново",
    404: "Не найдено",
    429: "Слишком много запросов — подождите секунду",
    500: "Ошибка на сервере. Попробуйте ещё раз",
    502: "Внешний сервис ответил ошибкой. Попробуйте позже",
    503: "Сервис временно недоступен",
  };
  return new ApiError(response.status, typeof detail === "string" ? detail : fallback[response.status] || "Что-то пошло не так");
}

// ---------- Запрос ----------

async function request(method, path, { json, form, auth = true, raw = false, retries = 3 } = {}) {
  const headers = {};
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = new URLSearchParams(form);
  }
  if (auth && session.token) headers.Authorization = `Bearer ${session.token}`;

  await nextSlot();
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { method, headers, body });
  } catch {
    throw new ApiError(0, "Нет связи с сервером. Проверьте интернет или что бэкенд запущен");
  }

  if (response.status === 429 && retries > 0) {
    const retryAfter = Number(response.headers.get("Retry-After")) || 1;
    await sleep(retryAfter * 1000);
    return request(method, path, { json, form, auth, raw, retries: retries - 1 });
  }

  if (response.status === 401 && auth) {
    // Токен истёк или пользователь удалён — на вход, потом вернёмся сюда же
    session.clear();
    const next = encodeURIComponent(location.pathname.split("/").pop() + location.search);
    location.href = `auth.html?next=${next}`;
    throw new ApiError(401, "Сессия истекла — войдите заново");
  }

  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return null;
  return raw ? response.text() : response.json();
}

// ---------- Эндпоинты ----------

export const api = {
  // Авторизация
  register: (data) => request("POST", "/auth/register", { json: data, auth: false }),
  verifyEmail: (email, code) => request("POST", "/auth/verify-email", { json: { email, code }, auth: false }),
  resendCode: (email) => request("POST", "/auth/resend-code", { json: { email }, auth: false }),
  login: (email, password) => request("POST", "/auth/login", { form: { username: email, password }, auth: false }),

  // Профиль
  me: () => request("GET", "/users/me"),
  updateMe: (data) => request("PATCH", "/users/me", { json: data }),
  deleteMe: () => request("DELETE", "/users/me"),

  // Справочники
  regions: () => request("GET", "/geo/regions", { auth: false }),
  popularCategories: (limit = 10) => request("GET", `/categories/popular?limit=${limit}`, { auth: false }),

  // Заказы (корзина)
  orders: ({ limit = 20, offset = 0, status } = {}) =>
    request("GET", `/orders?limit=${limit}&offset=${offset}${status ? `&status=${status}` : ""}`),
  createOrder: (topK = 3) => request("POST", "/orders", { json: { top_k: topK } }),
  order: (id) => request("GET", `/orders/${id}`),
  updateOrder: (id, data) => request("PATCH", `/orders/${id}`, { json: data }),
  setDelivery: (id, data = {}) => request("PUT", `/orders/${id}/delivery`, { json: data }),
  addItem: (id, data) => request("POST", `/orders/${id}/items`, { json: data }),
  updateItem: (id, itemId, data) => request("PATCH", `/orders/${id}/items/${itemId}`, { json: data }),
  removeItem: (id, itemId) => request("DELETE", `/orders/${id}/items/${itemId}`),
  startSearch: (id) => request("POST", `/orders/${id}/search`),
  results: (id) => request("GET", `/orders/${id}/results`),
  updateOffer: (offerId, data) => request("PATCH", `/offers/${offerId}`, { json: data }),

  // Письма
  letterTemplates: () => request("GET", "/letters/templates"),
  generateLetters: (orderId, offerIds, template) =>
    request("POST", `/orders/${orderId}/letters`, { json: { offer_ids: offerIds, ...(template ? { template } : {}) } }),
  letters: (orderId) => request("GET", `/orders/${orderId}/letters`),
  letterText: (letterId) => request("GET", `/letters/${letterId}/download`, { raw: true }),

  // Чат с агентом
  chat: (message, orderId) => request("POST", "/agent/chat", { json: { message, ...(orderId ? { order_id: orderId } : {}) } }),
  chatHistory: () => request("GET", "/agent/history"),
  clearChat: () => request("DELETE", "/agent/history"),
};

// Справочник регионов почти не меняется — кэшируем на сессию браузера
export async function getRegions() {
  try {
    const cached = sessionStorage.getItem("ff_regions");
    if (cached) return JSON.parse(cached);
  } catch {}
  const regions = await api.regions();
  try {
    sessionStorage.setItem("ff_regions", JSON.stringify(regions));
  } catch {}
  return regions;
}
