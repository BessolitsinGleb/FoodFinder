// Чат с Морковкой (агентом). Выдвижная панель + кнопка в углу.
// История хранится на сервере (Redis) и сама стирается через час тишины.
import { api } from "./api.js";
import { icon } from "./icons.js";
import { mascot } from "./mascot.js";
import { button, el, mount, renderMarkdown, toast } from "./utils.js";

const MAX_LENGTH = 4000;

export function initChat({ orderId = null, onReply } = {}) {
  let loaded = false;
  let sending = false;

  const messages = el("div", { class: "chat-messages", "aria-live": "polite" });
  const input = el("textarea", {
    class: "textarea",
    rows: 1,
    maxlength: MAX_LENGTH,
    placeholder: orderId ? "Спросите или попросите поправить корзину…" : "Спросите про поставщиков…",
    "aria-label": "Сообщение Морковке",
  });
  const send = el("button", { type: "submit", class: "btn btn-primary btn-icon", "aria-label": "Отправить" }, icon("send"));

  const suggestions = orderId
    ? ["Сравни поставщиков в моём заказе", "Поправь объём в корзине", "Какие документы запросить?"]
    : ["Какие документы запросить у поставщика?", "Как выбрать поставщика упаковки?", "На что смотреть в отзывах?"];

  const drawer = el("aside", { class: "chat-drawer", "aria-label": "Чат с помощником", "aria-hidden": "true" },
    el("div", { class: "chat-head" },
      mascot({ mood: "happy" }),
      el("div", { class: "grow" },
        el("h3", {}, "Морковка"),
        el("p", {}, orderId ? `Помощник по закупке №${orderId}` : "Помощник по закупкам"),
      ),
      el("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", title: "Очистить историю", "aria-label": "Очистить историю", onclick: clearHistory }, icon("trash")),
      el("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": "Закрыть чат", onclick: close }, icon("x")),
    ),
    messages,
    el("form", { class: "chat-compose", onsubmit: submit }, input, send),
  );

  const fab = el("button", { type: "button", class: "chat-fab", "aria-label": "Открыть чат с Морковкой", onclick: open },
    el("span", { class: "fab-avatar" }, mascot({ mood: "happy" })),
    el("span", { class: "fab-label" }, "Спросить Морковку"),
  );

  document.body.append(fab, drawer);

  input.addEventListener("keydown", (e) => {
    // Enter — отправить, Shift+Enter — новая строка
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      drawer.querySelector("form").requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer.classList.contains("open")) close();
  });

  function open() {
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    fab.hidden = true;
    if (!loaded) loadHistory();
    setTimeout(() => input.focus(), 300);
  }

  function close() {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    fab.hidden = false;
  }

  function scrollDown() {
    messages.scrollTop = messages.scrollHeight;
  }

  function bubble(role, content) {
    const node = role === "assistant"
      ? el("div", { class: "msg msg-assistant" }, renderMarkdown(content))
      : role === "error"
        ? el("div", { class: "msg msg-error" }, content)
        : el("div", { class: "msg msg-user" }, content);
    messages.append(node);
    scrollDown();
    return node;
  }

  function welcome() {
    mount(messages,
      el("div", { class: "msg msg-assistant" },
        el("p", {}, "Привет! Я Морковка 🥕 Помогу разобраться с поставщиками, документами и ценами."),
        orderId ? el("p", {}, "Если заметили ошибку в корзине — просто скажите, я поправлю.") : null,
      ),
      el("div", { class: "chat-suggestions" },
        suggestions.map((text) => el("button", { type: "button", class: "chip", onclick: () => sendMessage(text) }, text)),
      ),
    );
  }

  async function loadHistory() {
    loaded = true;
    mount(messages, el("div", { class: "page-loader", style: { padding: "40px 0" } }, el("div", { class: "spinner" })));
    try {
      const history = await api.chatHistory();
      if (!history.length) welcome();
      else {
        mount(messages);
        history.forEach((m) => bubble(m.role, m.content));
      }
    } catch (err) {
      mount(messages);
      bubble("error", err.status === 503 ? "Чат сейчас недоступен. Попробуйте позже." : err.message);
      loaded = false;
    }
  }

  async function clearHistory() {
    try {
      await api.clearChat();
      welcome();
      toast("История чата очищена");
    } catch (err) {
      toast(err.message, "error");
    }
  }

  function submit(e) {
    e.preventDefault();
    sendMessage(input.value);
  }

  async function sendMessage(text) {
    text = text.trim();
    if (!text || sending) return;
    sending = true;
    send.disabled = true;
    messages.querySelector(".chat-suggestions")?.remove();
    input.value = "";
    input.style.height = "";
    bubble("user", text);

    const typing = el("div", { class: "msg msg-assistant" }, el("span", { class: "typing", "aria-label": "Морковка печатает" }, el("i"), el("i"), el("i")));
    messages.append(typing);
    scrollDown();

    try {
      const { reply } = await api.chat(text, orderId);
      typing.remove();
      bubble("assistant", reply || "…");
      onReply?.();
    } catch (err) {
      typing.remove();
      bubble("error", err.status === 503 ? "Помощник сейчас недоступен. Попробуйте позже." : err.message);
      input.value = text; // чтобы не набирать заново
    } finally {
      sending = false;
      send.disabled = false;
      input.focus();
    }
  }

  return { open, close };
}

// Кнопка для страниц, где удобно открыть чат из текста
export function chatButton(chat, label = "Спросить Морковку") {
  return button(label, { variant: "soft", size: "sm", iconName: "chat", onclick: () => chat.open() });
}
