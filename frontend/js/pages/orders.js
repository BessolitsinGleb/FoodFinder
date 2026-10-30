// Мои закупки: история заказов и создание новой корзины.
import { api, session } from "../api.js";
import { initChat } from "../chat.js";
import { icon } from "../icons.js";
import { errorState, loadProfile, pageLoader, renderFooter, renderHeader, requireAuth } from "../layout.js";
import { mascot } from "../mascot.js";
import { $, button, el, formatDate, mount, plural, statusBadge, toast, withLoading } from "../utils.js";

const PAGE_SIZE = 20;
const FILTERS = [
  ["", "Все"],
  ["draft", "Черновики"],
  ["searching", "Ищем"],
  ["ready", "Готовы"],
  ["completed", "С письмами"],
];

const state = { status: "", items: [], total: 0, user: session.profile };
const page = $("#page");

if (requireAuth()) {
  renderHeader({ active: "orders" });
  renderFooter();
  initChat();
  start();
}

async function start() {
  mount(page, pageLoader());
  try {
    state.user = await loadProfile();
    await loadOrders(true);
  } catch (err) {
    mount(page, errorState(err.message, start));
  }
}

async function loadOrders(reset = false) {
  const offset = reset ? 0 : state.items.length;
  const data = await api.orders({ limit: PAGE_SIZE, offset, status: state.status || undefined });
  state.items = reset ? data.items : [...state.items, ...data.items];
  state.total = data.total;
  render();
}

async function createOrder(btn) {
  await withLoading(btn, async () => {
    try {
      const order = await api.createOrder(3);
      location.href = `order.html?id=${order.id}`;
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

function orderCard(order) {
  const titles = order.items.map((item) => item.title);
  const summary = titles.length
    ? titles.slice(0, 3).join(", ") + (titles.length > 3 ? ` и ещё ${titles.length - 3}` : "")
    : "Корзина пока пустая";
  return el("a", { class: "order-card", href: `order.html?id=${order.id}` },
    el("div", { class: "order-num" }, `№${order.id}`),
    el("div", { class: "grow" },
      el("h3", {}, summary),
      el("div", { class: "order-meta" },
        el("span", {}, icon("clock"), formatDate(order.created_at)),
        el("span", {}, icon("pin"), order.delivery_city),
        el("span", {}, icon("box"), `${order.items.length} ${plural(order.items.length, "позиция", "позиции", "позиций")}`),
      ),
    ),
    statusBadge(order.status),
  );
}

function render() {
  const firstName = (state.user?.name || "").split(" ")[0];
  const newButton = button("Новая закупка", { variant: "accent", size: "lg", iconName: "plus" });
  newButton.addEventListener("click", () => createOrder(newButton));

  const greeting = el("section", { class: "greeting" },
    mascot({ wave: true }),
    el("div", {},
      el("h1", {}, firstName ? `Привет, ${firstName}!` : "Привет!"),
      el("p", {}, "Соберите корзину — я найду поставщиков рядом и сравню их."),
    ),
    newButton,
  );

  const filters = el("div", { class: "chips filters", role: "group", "aria-label": "Фильтр по статусу" },
    FILTERS.map(([value, label]) =>
      el("button", {
        type: "button",
        class: "chip",
        "aria-pressed": String(state.status === value),
        onclick: async () => {
          state.status = value;
          try {
            await loadOrders(true);
          } catch (err) {
            toast(err.message, "error");
          }
        },
      }, label),
    ),
  );

  let list;
  if (!state.items.length) {
    list = el("div", { class: "card empty" },
      mascot({ mood: state.status ? "thinking" : "happy" }),
      el("h3", {}, state.status ? "Здесь пока пусто" : "Закупок ещё нет"),
      el("p", {}, state.status ? "Нет заказов с таким статусом." : "Начните с новой закупки — это займёт пару минут."),
    );
  } else {
    const more = state.items.length < state.total
      ? button(`Показать ещё (${state.total - state.items.length})`, { variant: "soft" })
      : null;
    more?.addEventListener("click", () => withLoading(more, () => loadOrders(false).catch((err) => toast(err.message, "error"))));
    list = el("div", { class: "stack" },
      el("div", { class: "order-list" }, state.items.map(orderCard)),
      more && el("div", { class: "row", style: { justifyContent: "center" } }, more),
    );
  }

  mount(page,
    greeting,
    el("div", { class: "section-title" }, el("h2", {}, "Мои закупки"), el("span", { class: "muted small" }, `Всего: ${state.total}`)),
    filters,
    list,
  );
}
