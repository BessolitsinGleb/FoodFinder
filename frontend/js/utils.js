import { icon } from "./icons.js";

// ---------- DOM ----------

// Создание элементов без innerHTML: всё, что пришло от пользователя или из интернета,
// попадает в страницу только как текст. Так XSS из названий поставщиков невозможен.
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key === "style" && typeof value === "object") {
      // CSS-переменные (--value) задаются только через setProperty
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith("--")) node.style.setProperty(prop, String(v));
        else node.style[prop] = v;
      }
    }
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "selected") node[key] = Boolean(value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, String(value));
  }
  append(node, children);
  return node;
}

function append(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
  return node;
}

export function mount(node, ...children) {
  clear(node);
  append(node, children);
  return node;
}

export const $ = (selector, root = document) => root.querySelector(selector);

// Кнопка с иконкой
export function button(label, { variant = "", size = "", iconName, type = "button", ...props } = {}) {
  const cls = ["btn", variant && `btn-${variant}`, size && `btn-${size}`, props.class].filter(Boolean).join(" ");
  delete props.class;
  return el("button", { type, class: cls, ...props }, iconName ? icon(iconName) : null, label);
}

// Блокирует кнопку и показывает спиннер, пока идёт запрос
export async function withLoading(btn, action) {
  if (btn.disabled) return;
  const saved = [...btn.childNodes];
  btn.disabled = true;
  mount(btn, el("span", { class: "spinner" }), saved.filter((n) => n.nodeType === Node.TEXT_NODE));
  try {
    return await action();
  } finally {
    btn.disabled = false;
    mount(btn, saved);
  }
}

// ---------- Форматирование ----------

const moneyFormat = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 });

export const formatMoney = (value) => (value == null ? "—" : moneyFormat.format(Number(value)));
export const formatNumber = (value) => (value == null ? "" : numberFormat.format(Number(value)));

export function formatQty(quantity, unit) {
  if (quantity == null) return "";
  return `${formatNumber(quantity)} ${unit || ""}`.trim();
}

export function formatDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export function formatDateTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function plural(n, one, few, many) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

// Ссылки только http(s): "javascript:" из данных поставщика не пройдёт
export function safeUrl(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url.includes("://") ? url : `https://${url}`);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

export function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// ---------- Статусы заказа ----------

export const ORDER_STATUS = {
  draft: { label: "Черновик", tone: "" },
  searching: { label: "Идёт поиск", tone: "info", pulse: true },
  ready: { label: "Подборка готова", tone: "success" },
  failed: { label: "Поиск не удался", tone: "danger" },
  completed: { label: "Письма готовы", tone: "primary" },
  cancelled: { label: "Отменён", tone: "" },
};
export const EDITABLE_STATUSES = new Set(["draft", "ready", "failed"]);

export function statusBadge(status) {
  const info = ORDER_STATUS[status] || { label: status, tone: "" };
  const cls = ["badge", "badge-dot", info.tone && `badge-${info.tone}`, info.pulse && "badge-pulse"].filter(Boolean).join(" ");
  return el("span", { class: cls }, info.label);
}

export const UNITS = ["кг", "т", "г", "л", "мл", "шт", "тыс шт"];

// ---------- Уведомления ----------

function toastRoot() {
  let root = $(".toasts");
  if (!root) {
    root = el("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(root);
  }
  return root;
}

export function toast(message, type = "info", timeout = 3800) {
  const node = el("div", { class: `toast toast-${type}` },
    icon(type === "error" ? "alert" : type === "success" ? "check" : "info"), message);
  toastRoot().append(node);
  setTimeout(() => {
    node.classList.add("leaving");
    node.addEventListener("animationend", () => node.remove(), { once: true });
  }, timeout);
}

// Модальное подтверждение вместо confirm(): в стиле сайта и с понятными кнопками
export function confirmDialog({ title, text, confirmLabel = "Подтвердить", danger = false }) {
  return new Promise((resolve) => {
    const close = (result) => {
      backdrop.remove();
      document.removeEventListener("keydown", onKey);
      resolve(result);
    };
    const onKey = (e) => e.key === "Escape" && close(false);
    const ok = button(confirmLabel, { variant: danger ? "danger" : "primary", onclick: () => close(true) });
    const backdrop = el("div", { class: "modal-backdrop", onclick: (e) => e.target === backdrop && close(false) },
      el("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
        el("h3", {}, title),
        text && el("p", { class: "muted" }, text),
        el("div", { class: "row end" }, button("Отмена", { variant: "ghost", onclick: () => close(false) }), ok),
      ),
    );
    document.addEventListener("keydown", onKey);
    document.body.append(backdrop);
    ok.focus();
  });
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---------- Мини-markdown для ответов агента ----------
// Модель отвечает в markdown. Разбираем только безопасное подмножество
// (заголовки, списки, **жирный**, `код`, ссылки http) и строим DOM из текста — без innerHTML.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|https?:\/\/[^\s)<>\]]+)/g;

function inline(text) {
  const parts = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const token = match[0];
    if (token.startsWith("**")) parts.push(el("strong", {}, token.slice(2, -2)));
    else if (token.startsWith("`")) parts.push(el("code", {}, token.slice(1, -1)));
    else {
      const url = safeUrl(token);
      parts.push(url ? el("a", { href: url, target: "_blank", rel: "noopener noreferrer nofollow" }, hostOf(url)) : token);
    }
    last = match.index + token.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

export function renderMarkdown(text) {
  const root = el("div", { class: "md" });
  let list = null;
  let paragraph = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      root.append(el("p", {}, paragraph.flatMap((line, i) => [i ? el("br") : null, ...inline(line)])));
      paragraph = [];
    }
  };
  const flushList = () => {
    list = null;
  };

  for (const raw of (text || "").split("\n")) {
    const line = raw.trimEnd();
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);

    if (!line.trim()) {
      flushParagraph();
      flushList();
    } else if (heading) {
      flushParagraph();
      flushList();
      root.append(el("h4", {}, inline(heading[1].replace(/\*\*/g, ""))));
    } else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      flushParagraph();
      flushList();
      root.append(el("hr"));
    } else if (bullet || numbered) {
      flushParagraph();
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = el(tag);
        root.append(list);
      }
      list.append(el("li", {}, inline((bullet || numbered)[1])));
    } else if (/^\|.*\|$/.test(line.trim())) {
      // Таблицы markdown показываем как моноширинный текст — читаемо и безопасно
      flushParagraph();
      flushList();
      if (!/^\|[\s:-|]+\|$/.test(line.trim())) root.append(el("pre", { class: "md-table" }, line.trim()));
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  return root;
}
