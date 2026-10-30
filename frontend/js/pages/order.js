// Страница закупки: корзина -> адрес -> поиск -> подборка -> письма.
import { api } from "../api.js";
import { SEARCH_POLL_MS } from "../config.js";
import { chatButton, initChat } from "../chat.js";
import { icon } from "../icons.js";
import { errorState, field, pageLoader, regionSelect, renderFooter, renderHeader, requireAuth, showFieldErrors } from "../layout.js";
import { mascot } from "../mascot.js";
import {
  $, EDITABLE_STATUSES, UNITS, button, confirmDialog, el, formatDate, formatMoney, formatNumber, formatQty,
  hostOf, mount, plural, safeUrl, statusBadge, toast, withLoading,
} from "../utils.js";

const orderId = Number(new URLSearchParams(location.search).get("id"));
const page = $("#page");

const state = {
  order: null,
  results: null, // ответ /results
  letters: [],
  popular: null, // популярные категории + "Другое"
  templates: null,
  picker: null, // выбранная в каталоге категория (CategoryOption)
  editingItem: null, // id позиции в режиме редактирования
  deliveryForm: false, // открыта форма "другой адрес"
  pollTimer: null,
};

const editable = () => EDITABLE_STATUSES.has(state.order.status);
let chat = null;

if (requireAuth()) {
  renderHeader({ active: "orders" });
  renderFooter();
  if (!orderId) mount(page, errorState("В адресе нет номера закупки."));
  else {
    // После ответа агента перечитываем заказ: он мог поправить корзину
    chat = initChat({ orderId, onReply: () => reload().catch(() => {}) });
    start();
  }
}

// ---------- Загрузка ----------

async function start() {
  mount(page, pageLoader("Открываем закупку…"));
  try {
    await reload();
    if (state.order.status === "searching") startPolling();
  } catch (err) {
    mount(page, errorState(err.status === 404 ? "Такой закупки нет или она принадлежит другому пользователю." : err.message, err.status === 404 ? null : start));
  }
}

async function reload() {
  state.order = await api.order(orderId);
  const { status, searched_at: searchedAt } = state.order;
  if (editable() && !state.popular) state.popular = await api.popularCategories(10);
  // Подборка есть, если поиск уже хоть раз завершался
  state.results = searchedAt || ["ready", "completed"].includes(status) ? await api.results(orderId) : null;
  state.letters = status === "completed" ? await api.letters(orderId) : [];
  render();
}

// ---------- Действия ----------

async function act(btn, action, successMessage) {
  const run = async () => {
    try {
      await action();
      if (successMessage) toast(successMessage, "success");
    } catch (err) {
      toast(err.message, "error");
      throw err;
    }
  };
  return btn ? withLoading(btn, run).catch(() => {}) : run().catch(() => {});
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      const order = await api.order(orderId);
      state.order = order;
      if (order.status === "searching") {
        const box = $("#progress");
        if (box) mount(box, progressContent());
        return;
      }
      stopPolling();
      await reload();
      if (order.status === "ready") toast("Подборка готова! 🥕", "success", 5000);
      else if (order.status === "failed") toast("Поиск не удался — подробности на странице", "error");
    } catch {
      // временная ошибка сети — попробуем на следующем тике
    }
  }, SEARCH_POLL_MS);
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

// ---------- Отрисовка ----------

function render() {
  const { order } = state;
  const head = el("div", { class: "page-head" },
    el("div", {},
      el("div", { class: "row" }, el("h1", {}, `Закупка №${order.id}`), statusBadge(order.status)),
      el("p", {}, `Создана ${formatDate(order.created_at)}`),
    ),
    editable() ? button("Отменить закупку", { variant: "ghost", size: "sm", iconName: "x", onclick: cancelOrder }) : null,
  );

  const main = el("div", { class: "stack-lg" },
    !order.delivery_confirmed && editable() ? deliveryQuestion() : null,
    order.status === "searching" ? progressCard() : null,
    order.status === "failed" ? failedCard() : null,
    cartCard(),
    state.results ? resultsSection() : null,
    order.status === "completed" ? lettersSection() : null,
  );

  mount(page,
    el("a", { class: "back-link", href: "orders.html" }, icon("back"), "Мои закупки"),
    head,
    el("div", { class: "order-layout" }, main, sidebar()),
  );
}

// --- Вопрос про доставку ---

function deliveryQuestion() {
  const { order } = state;
  const card = el("section", { class: "card" });
  const bubble = el("div", { class: "speech-bubble" },
    el("p", { class: "strong" }, `Доставка в г. ${order.delivery_city} (${order.delivery_region})?`),
    el("p", { class: "muted small" }, "С этого места начну искать поставщиков. Если нужен другой адрес — укажите его, так поиск будет точнее."),
  );
  const yes = button("Да, всё верно", { variant: "primary", iconName: "check" });
  yes.addEventListener("click", () => act(yes, async () => {
    state.order = await api.setDelivery(orderId, {});
    render();
  }, "Адрес подтверждён"));
  const other = button("Другой адрес", { variant: "soft", iconName: "pin", onclick: () => { state.deliveryForm = true; render(); } });

  mount(card,
    el("div", { class: "speech" }, mascot({ mood: "thinking" }), bubble),
    state.deliveryForm ? deliveryForm() : el("div", { class: "row", style: { marginTop: "16px" } }, yes, other),
  );
  return card;
}

function deliveryForm() {
  const { order } = state;
  const city = el("input", { class: "input", name: "city", id: "d-city", value: order.delivery_city, required: true });
  const address = el("input", { class: "input", name: "address", id: "d-address", value: order.delivery_address || "", placeholder: "Улица, дом — необязательно", maxlength: 500 });
  const regionHolder = el("div", {}, el("div", { class: "skeleton", style: { height: "46px" } }));
  regionSelect({ value: order.delivery_region, id: "d-region" }).then((select) => regionHolder.replaceWith(field("Регион", select)));

  const save = button("Сохранить адрес", { variant: "primary", type: "submit" });
  const form = el("form", { class: "add-form", style: { marginTop: "16px" }, novalidate: true },
    el("div", { class: "form-grid" },
      field("Город", city),
      regionHolder,
      el("div", { class: "span-2" }, field("Адрес доставки", address, { hint: "Точный адрес помогает найти поставщиков ближе к вам" })),
    ),
    el("div", { class: "row end", style: { marginTop: "14px" } },
      button("Отмена", { variant: "ghost", onclick: () => { state.deliveryForm = false; render(); } }),
      save,
    ),
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const region = form.querySelector("#d-region");
    const data = { city: city.value.trim(), address: address.value.trim() || null, ...(region?.value ? { region: region.value } : {}) };
    if (!data.city) return showFieldErrors(form, { city: "укажите город" });
    act(save, async () => {
      try {
        state.order = await api.setDelivery(orderId, data);
      } catch (err) {
        showFieldErrors(form, err.fields);
        throw err;
      }
      state.deliveryForm = false;
      render();
    }, "Адрес доставки сохранён");
  });
  return form;
}

// --- Прогресс поиска ---

function progressContent() {
  const progress = Object.entries(state.order.search_progress || {});
  const done = progress.filter(([, p]) => p.status === "done" || p.status === "failed").length;
  const icons = {
    pending: el("span", { class: "status-dot" }, icon("clock")),
    searching: el("span", { class: "status-dot searching" }, el("span", { class: "spinner" })),
    done: el("span", { class: "status-dot done" }, icon("check")),
    failed: el("span", { class: "status-dot failed" }, icon("x")),
  };
  const labels = { pending: "в очереди", searching: "ищу…", done: "готово", failed: "не удалось" };
  return [
    mascot({ mood: "thinking" }),
    el("h2", {}, "Ищу поставщиков…"),
    el("p", { class: "muted" }, "Сначала рядом с вами, потом по региону и округу. Проверяю документы и отзывы. ",
      "Обычно 1–2 минуты на позицию — можно закрыть страницу, поиск продолжится."),
    el("div", { class: "meter accent" }, el("span", { style: { width: `${progress.length ? Math.max(8, (done / progress.length) * 100) : 8}%` } })),
    el("div", { class: "progress-list" },
      progress.map(([, p]) =>
        el("div", { class: "progress-item" },
          icons[p.status]?.cloneNode(true) || icons.pending.cloneNode(true),
          el("span", { class: "grow" }, p.title),
          el("span", { class: "small muted" },
            p.status === "done" ? `найдено: ${p.found}` : labels[p.status] || p.status),
        ),
      ),
    ),
  ];
}

function progressCard() {
  return el("section", { class: "card progress-card", id: "progress", "aria-live": "polite" }, progressContent());
}

function failedCard() {
  return el("div", { class: "alert alert-danger" }, icon("alert"),
    el("div", {},
      el("div", { class: "strong" }, "Поиск не удался"),
      el("div", {}, state.order.search_error || "Попробуйте запустить поиск ещё раз."),
    ),
  );
}

// --- Корзина ---

function cartCard() {
  const { order } = state;
  const canEdit = editable();
  const card = el("section", { class: "card" });

  const title = el("div", { class: "section-title" },
    el("h2", {}, "Корзина"),
    el("span", { class: "muted small" }, `${order.items.length} ${plural(order.items.length, "позиция", "позиции", "позиций")}`),
  );

  const staleNote = state.results && order.status === "draft" && order.searched_at
    ? el("div", { class: "alert alert-warning" }, icon("info"), "Корзина изменилась после поиска — запустите поиск заново, чтобы обновить подборку.")
    : null;

  const items = order.items.length
    ? el("div", { class: "items" }, order.items.map((item) => state.editingItem === item.id ? itemEditor(item) : itemRow(item, canEdit)))
    : el("div", { class: "empty", style: { padding: "20px" } },
        el("p", {}, canEdit ? "Добавьте, что нужно закупить: выберите категорию ниже или «Другое»." : "Корзина пуста."));

  mount(card, title, staleNote, items, canEdit ? picker() : null);
  return card;
}

function itemRow(item, canEdit) {
  return el("div", { class: "item" },
    el("div", { class: "item-icon" }, icon("box")),
    el("div", { class: "grow" },
      el("h4", {}, item.title),
      item.details ? el("div", { class: "item-details" }, item.details) : null,
    ),
    item.quantity != null ? el("span", { class: "qty" }, formatQty(item.quantity, item.unit)) : el("span", { class: "faint small" }, "объём не указан"),
    canEdit
      ? el("div", { class: "item-actions" },
          el("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": `Изменить «${item.title}»`, onclick: () => { state.editingItem = item.id; render(); } }, icon("edit")),
          el("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": `Удалить «${item.title}»`, onclick: () => removeItem(item) }, icon("trash")),
        )
      : null,
  );
}

function quantityFields(item = {}) {
  const quantity = el("input", { class: "input", type: "number", name: "quantity", id: `qty-${item.id || "new"}`, min: "0", step: "any", inputmode: "decimal", value: item.quantity != null ? Number(item.quantity) : "", placeholder: "Например, 500" });
  const unit = el("select", { class: "select", name: "unit", id: `unit-${item.id || "new"}` },
    UNITS.map((u) => el("option", { value: u, selected: (item.unit || "кг") === u }, u)));
  return { quantity, unit };
}

function itemEditor(item) {
  const details = el("textarea", { class: "textarea", name: "details", id: `details-${item.id}`, maxlength: 1000 }, item.details || "");
  const { quantity, unit } = quantityFields(item);
  const save = button("Сохранить", { variant: "primary", size: "sm", type: "submit" });
  const form = el("form", { class: "item editing", novalidate: true },
    el("h4", {}, item.title),
    el("div", { class: "form-grid" },
      el("div", { class: "span-2" }, field("Требования", details)),
      field("Объём", quantity),
      field("Единица", unit),
    ),
    el("div", { class: "row end" },
      button("Отмена", { variant: "ghost", size: "sm", onclick: () => { state.editingItem = null; render(); } }),
      save,
    ),
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = { details: details.value.trim() || null };
    if (quantity.value) {
      data.quantity = quantity.value;
      data.unit = unit.value;
    }
    act(save, async () => {
      try {
        state.order = await api.updateItem(orderId, item.id, data);
      } catch (err) {
        showFieldErrors(form, err.fields);
        throw err;
      }
      state.editingItem = null;
      render();
    }, "Позиция обновлена");
  });
  return form;
}

async function removeItem(item) {
  const ok = await confirmDialog({ title: "Удалить позицию?", text: `«${item.title}» уберём из корзины.`, confirmLabel: "Удалить", danger: true });
  if (!ok) return;
  act(null, async () => {
    state.order = await api.removeItem(orderId, item.id);
    render();
  }, "Позиция удалена");
}

function picker() {
  const options = state.popular || [];
  const selected = state.picker;
  const wrap = el("div", { class: "picker", style: { marginTop: "20px" } },
    el("div", { class: "label" }, "Что добавить?"),
    el("div", { class: "chips" },
      options.map((option) =>
        el("button", {
          type: "button",
          class: option.is_other ? "chip chip-other" : "chip",
          "aria-pressed": String(selected?.slug === option.slug),
          onclick: () => {
            state.picker = selected?.slug === option.slug ? null : option;
            render();
            $("#new-title, #details-new")?.focus();
          },
        }, option.is_other ? [icon("plus"), option.name] : option.name),
      ),
    ),
  );
  if (selected) wrap.append(addForm(selected));
  return wrap;
}

function addForm(option) {
  const customTitle = option.is_other
    ? el("input", { class: "input", name: "custom_title", id: "new-title", maxlength: 200, required: true, placeholder: "Например, крафт-пакеты 2 кг" })
    : null;
  const details = el("textarea", { class: "textarea", name: "details", id: "details-new", maxlength: 1000, placeholder: "Жирность, сорт, ГОСТ, фасовка, сертификаты…" });
  const { quantity, unit } = quantityFields();
  const add = button("Добавить в корзину", { variant: "primary", type: "submit", iconName: "plus" });

  const form = el("form", { class: "add-form", novalidate: true },
    el("div", { class: "row between", style: { marginBottom: "12px" } },
      el("h3", { style: { margin: 0 } }, option.is_other ? "Свой товар" : option.name),
      el("button", { type: "button", class: "btn btn-ghost btn-icon btn-sm", "aria-label": "Закрыть", onclick: () => { state.picker = null; render(); } }, icon("x")),
    ),
    el("div", { class: "form-grid" },
      customTitle ? el("div", { class: "span-all" }, field("Что ищем", customTitle)) : null,
      el("div", { class: "span-all" }, field("Требования", details, { hint: "Чем подробнее, тем точнее подберём" })),
      field("Объём", quantity, { hint: "Можно оставить пустым" }),
      field("Единица", unit),
    ),
    el("div", { class: "row end", style: { marginTop: "14px" } }, add),
  );

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = option.is_other ? { custom_title: customTitle.value.trim() } : { category_id: option.id };
    if (option.is_other && data.custom_title.length < 2) return showFieldErrors(form, { custom_title: "опишите товар" });
    if (details.value.trim()) data.details = details.value.trim();
    if (quantity.value) {
      if (Number(quantity.value) <= 0) return showFieldErrors(form, { quantity: "должно быть больше 0" });
      data.quantity = quantity.value;
      data.unit = unit.value;
    }
    act(add, async () => {
      try {
        state.order = await api.addItem(orderId, data);
      } catch (err) {
        showFieldErrors(form, err.fields);
        throw err;
      }
      state.picker = null;
      render();
    }, "Добавлено в корзину");
  });
  return form;
}

async function cancelOrder() {
  const ok = await confirmDialog({ title: "Отменить закупку?", text: "Её нельзя будет изменить или запустить поиск.", confirmLabel: "Отменить закупку", danger: true });
  if (!ok) return;
  act(null, async () => {
    state.order = await api.updateOrder(orderId, { status: "cancelled" });
    render();
  }, "Закупка отменена");
}

// --- Боковая панель ---

function sidebar() {
  const { order } = state;
  const canEdit = editable();

  const delivery = el("div", { class: "card card-tight side-block" },
    el("h3", {}, icon("truck"), "Доставка"),
    el("p", { class: "strong" }, `${order.delivery_city}, ${order.delivery_region}`),
    order.delivery_address ? el("p", { class: "small muted" }, order.delivery_address) : null,
    el("p", { class: "small" }, order.delivery_confirmed ? el("span", { class: "badge badge-success" }, icon("check"), "подтверждено") : el("span", { class: "badge badge-warning" }, "нужно подтвердить")),
    canEdit && order.delivery_confirmed
      ? button("Изменить", { variant: "ghost", size: "sm", iconName: "edit", onclick: () => { state.order = { ...order, delivery_confirmed: false }; state.deliveryForm = true; render(); } })
      : null,
  );

  const topK = el("div", { class: "card card-tight side-block" },
    el("h3", {}, icon("award"), "Сколько поставщиков показать"),
    el("p", { class: "small muted" }, "Лучших на каждую позицию"),
    el("div", { class: "segmented", role: "group", "aria-label": "Количество поставщиков" },
      [1, 2, 3, 4, 5].map((k) =>
        el("button", {
          type: "button",
          "aria-pressed": String(order.top_k === k),
          disabled: !canEdit,
          onclick: () => order.top_k !== k && act(null, async () => {
            state.order = await api.updateOrder(orderId, { top_k: k });
            render();
          }),
        }, String(k)),
      ),
    ),
  );

  const blocks = [delivery, topK, searchBlock()];
  if (state.results?.estimated_total != null) {
    const { estimated_total: total, priced_items: priced, items } = state.results;
    blocks.push(el("div", { class: "card card-tight side-block" },
      el("h3", {}, icon("scale"), "Примерная сумма"),
      el("div", { class: "total-sum" }, formatMoney(total)),
      el("p", { class: "small muted" }, `Посчитано для ${priced} из ${items.length} ${plural(items.length, "позиции", "позиций", "позиций")} — по выбранным или лучшим предложениям, где цена известна.`),
    ));
  }
  return el("aside", { class: "order-side" }, blocks);
}

function searchBlock() {
  const { order } = state;
  if (order.status === "searching") {
    return el("div", { class: "card card-tight side-block" },
      el("h3", {}, icon("search"), "Поиск идёт"),
      el("p", { class: "small muted" }, "Подборка появится здесь автоматически."));
  }
  if (!editable()) {
    return el("div", { class: "card card-tight side-block" },
      el("h3", {}, icon("chat"), "Есть вопросы?"),
      el("p", { class: "small muted" }, "Морковка поможет сравнить поставщиков и подскажет, что спросить."),
      chatButton(chat, "Обсудить с Морковкой"));
  }

  const reasons = [];
  if (!order.items.length) reasons.push("добавьте хотя бы одну позицию");
  if (!order.delivery_confirmed) reasons.push("подтвердите адрес доставки");
  const again = Boolean(order.searched_at);
  const start = button(again ? "Искать заново" : "Найти поставщиков", { variant: "accent", size: "lg", iconName: "search", class: "btn-block", disabled: reasons.length > 0 });
  start.addEventListener("click", () => act(start, async () => {
    state.order = await api.startSearch(orderId);
    render();
    startPolling();
  }));

  return el("div", { class: "card card-tight side-block" },
    el("h3", {}, icon("search"), "Поиск"),
    start,
    reasons.length
      ? el("p", { class: "small muted", style: { marginTop: "8px" } }, `Чтобы начать: ${reasons.join(" и ")}.`)
      : el("p", { class: "small muted", style: { marginTop: "8px" } }, "Займёт 1–2 минуты на позицию."),
  );
}

// ---------- Подборка ----------

const MATCH_LABELS = { exact: "Точное совпадение", partial: "Близкий товар", weak: "Смежный товар" };
const SCORE_LABELS = {
  match: "Соответствие товару",
  proximity: "Близость к вам",
  safety: "Безопасность",
  price: "Цена",
  delivery_time: "Указан срок доставки",
  completeness: "Полнота данных",
};
const SAFETY_LABELS = {
  documents: "Документы",
  legal: "ИНН найден",
  reviews: "Отзывы",
  popularity: "Упоминания на других сайтах",
  age: "Возраст компании",
};

function resultsSection() {
  const { items } = state.results;
  const selectedCount = items.flatMap((i) => i.offers).filter((o) => o.is_selected).length;
  const canWrite = ["ready", "completed"].includes(state.order.status);

  const lettersButton = canWrite
    ? button(selectedCount ? `Письма выбранным (${selectedCount})` : "Выберите поставщиков для писем", {
        variant: "primary",
        iconName: "file",
        disabled: !selectedCount,
      })
    : null;
  lettersButton?.addEventListener("click", () => generateLetters(lettersButton));

  return el("section", { class: "stack" },
    el("div", { class: "section-title" }, el("h2", {}, "Подборка поставщиков"), lettersButton),
    el("p", { class: "muted small", style: { margin: 0 } },
      "Оценка считается по формуле: соответствие товару, близость, безопасность, цена и полнота данных. ",
      "Отметьте подходящих — подготовлю им письма-запросы."),
    items.map(resultItem),
  );
}

function resultItem({ item, offers }) {
  return el("div", { class: "result-item" },
    el("div", { class: "result-item-head" },
      el("h3", {}, item.title, item.details ? el("span", { class: "muted", style: { fontWeight: 600 } }, ` · ${item.details}`) : null),
      item.quantity != null ? el("span", { class: "badge" }, formatQty(item.quantity, item.unit)) : null,
    ),
    offers.length
      ? el("div", { class: "offers" }, offers.map(offerCard))
      : el("div", { class: "card empty" }, mascot({ mood: "sad" }), el("p", {}, "По этой позиции подходящих поставщиков не нашлось. Попробуйте уточнить требования или расширить формулировку.")),
  );
}

function rating(value) {
  const n = Number(value || 0);
  return el("span", { class: "rating", title: `Безопасность ${formatNumber(n)} из 5` },
    [1, 2, 3, 4, 5].map((i) => el("i", {}, el("b", { style: { width: `${Math.max(0, Math.min(1, n - i + 1)) * 100}%` } }))),
    el("span", {}, formatNumber(n)),
  );
}

function bars(breakdown, labels) {
  return el("div", { class: "breakdown" },
    Object.entries(labels).filter(([key]) => key in (breakdown || {})).map(([key, label]) => {
      const value = Math.round((breakdown[key] || 0) * 100);
      return el("div", { class: "breakdown-row" },
        el("span", {}, label),
        el("div", { class: "meter" }, el("span", { style: { width: `${value}%` } })),
        el("b", {}, `${value}%`),
      );
    }),
  );
}

function fact(label, value, muted = false) {
  return el("div", { class: "fact" },
    el("div", { class: "fact-label" }, label),
    el("div", { class: `fact-value${muted ? " muted" : ""}` }, value),
  );
}

function offerCard(offer) {
  const s = offer.supplier;
  const website = safeUrl(s.website);
  const place = [s.city, s.region].filter(Boolean).join(", ");
  const price = offer.price != null ? `${formatMoney(offer.price)} / ${offer.price_unit || "ед."}` : null;

  const badges = el("div", { class: "badges" },
    s.is_safe ? el("span", { class: "badge badge-success" }, icon("shield"), "Безопасный") : null,
    s.is_popular ? el("span", { class: "badge badge-accent" }, icon("star"), "Популярный") : null,
    MATCH_LABELS[offer.match_level] ? el("span", { class: "badge" }, MATCH_LABELS[offer.match_level]) : null,
  );

  const contacts = el("div", { class: "contacts" },
    s.phones.slice(0, 3).map((phone) => el("a", { href: `tel:${phone.replace(/[^\d+]/g, "")}` }, icon("phone"), phone)),
    s.emails.slice(0, 2).map((email) => el("a", { href: `mailto:${encodeURIComponent(email)}` }, icon("mail"), email)),
    website ? el("a", { href: website, target: "_blank", rel: "noopener noreferrer nofollow" }, icon("link"), hostOf(website)) : null,
    s.inn ? el("span", { class: "muted" }, `ИНН ${s.inn}`) : null,
  );

  const sources = [...new Set([offer.source_url, ...s.sources].filter(Boolean))].map(safeUrl).filter(Boolean).slice(0, 8);

  // Заметка сохраняется, когда пользователь уходит из поля
  const note = el("textarea", { class: "textarea", maxlength: 2000, placeholder: "Заметка: созвонились, ждём прайс…", "aria-label": `Заметка о «${s.name}»` }, offer.user_note || "");
  note.addEventListener("blur", () => {
    const value = note.value.trim() || null;
    if (value === (offer.user_note || null)) return;
    act(null, async () => {
      const updated = await api.updateOffer(offer.id, { user_note: value });
      offer.user_note = updated.user_note;
    }, "Заметка сохранена");
  });

  const checkbox = el("input", { type: "checkbox", checked: offer.is_selected });
  checkbox.addEventListener("change", () => act(null, async () => {
    try {
      const updated = await api.updateOffer(offer.id, { is_selected: checkbox.checked });
      offer.is_selected = updated.is_selected;
      render(); // пересчитать сумму и кнопку писем
    } catch (err) {
      checkbox.checked = !checkbox.checked;
      throw err;
    }
  }));

  return el("article", { class: `offer${offer.is_selected ? " selected" : ""}` },
    el("div", { class: "offer-top" },
      el("div", { class: `rank rank-${offer.rank}` }, offer.rank ?? "–"),
      el("div", { class: "grow" },
        el("h4", {}, s.name),
        place ? el("span", { class: "place" }, icon("pin"), place) : el("span", { class: "place" }, icon("pin"), "город не указан"),
        badges,
      ),
      el("div", { class: "score", style: { "--value": Number(offer.score) }, title: "Итоговая оценка из 100" },
        el("span", {}, Math.round(Number(offer.score)), el("small", {}, "из 100"))),
    ),
    el("div", { class: "facts" },
      fact("Безопасность", rating(s.safety_rating)),
      fact("Цена", price || "не указана", !price),
      fact("Примерно за ваш объём", offer.estimated_cost != null ? formatMoney(offer.estimated_cost) : "—", offer.estimated_cost == null),
      fact("Мин. партия", offer.moq != null ? formatQty(offer.moq, offer.moq_unit) : "не указана", offer.moq == null),
      fact("Срок доставки", s.delivery_time || "не указан", !s.delivery_time),
    ),
    offer.product_name ? el("p", { class: "small" }, el("b", {}, "Товар: "), offer.product_name) : null,
    offer.agent_summary ? el("p", { class: "summary" }, offer.agent_summary) : null,
    contacts,
    s.red_flags.length
      ? el("div", { class: "alert alert-warning", style: { marginBottom: "12px" } }, icon("alert"),
          el("div", {}, el("div", { class: "strong" }, "Обратите внимание"), s.red_flags.join("; ")))
      : null,
    el("div", { class: "offer-more" },
      s.certificates.length ? el("div", { class: "chips" }, s.certificates.slice(0, 8).map((c) => el("span", { class: "chip chip-static" }, c))) : null,
      s.delivery_terms ? el("p", { class: "small muted", style: { margin: 0 } }, el("b", {}, "Доставка: "), s.delivery_terms) : null,
      el("details", {},
        el("summary", {}, "Почему такая оценка"),
        bars(offer.score_breakdown, SCORE_LABELS),
        s.safety_breakdown ? el("p", { class: "small strong", style: { margin: "12px 0 0" } }, "Из чего сложилась безопасность") : null,
        s.safety_breakdown ? bars(s.safety_breakdown, SAFETY_LABELS) : null,
      ),
      sources.length
        ? el("details", {},
            el("summary", {}, `Источники (${sources.length})`),
            el("div", { class: "sources" }, sources.map((url) => el("a", { href: url, target: "_blank", rel: "noopener noreferrer nofollow" }, hostOf(url) + new URL(url).pathname.replace(/\/$/, "").slice(0, 60)))),
          )
        : null,
    ),
    el("div", { class: "offer-footer" },
      el("div", { class: "grow" }, note),
      ["ready", "completed"].includes(state.order.status)
        ? el("label", { class: "checkbox" }, checkbox, "Выбрать для письма")
        : null,
    ),
  );
}

// ---------- Письма ----------

async function generateLetters(btn) {
  const offerIds = state.results.items.flatMap((i) => i.offers).filter((o) => o.is_selected).map((o) => o.id);
  if (!offerIds.length) return;
  await act(btn, async () => {
    if (!state.templates) state.templates = await api.letterTemplates();
    const template = state.templates.includes("default") ? "default" : state.templates[0];
    await api.generateLetters(orderId, offerIds, template);
    await reload();
    $("#letters")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, "Письма готовы — осталось вписать свои контакты");
}

function supplierName(supplierId) {
  for (const { offers } of state.results?.items || []) {
    const offer = offers.find((o) => o.supplier.id === supplierId);
    if (offer) return offer.supplier.name;
  }
  return "Поставщик";
}

function highlightPlaceholders(text) {
  // [ФИО], [Телефон] и т.п. подсвечиваем — их нужно заполнить вручную
  return text.split(/(\[[^\]\n]{1,40}\])/g).map((part) =>
    /^\[[^\]]+\]$/.test(part) ? el("span", { class: "placeholder-hint" }, part) : part);
}

function lettersSection() {
  const letters = state.letters;
  return el("section", { class: "card", id: "letters" },
    el("div", { class: "section-title" }, el("h2", {}, "Письма-запросы"), el("span", { class: "muted small" }, `${letters.length}`)),
    el("div", { class: "alert", style: { marginBottom: "16px" } }, icon("info"),
      el("div", {}, "Поля в квадратных скобках — ", el("span", { class: "placeholder-hint" }, "[ФИО]"), ", ",
        el("span", { class: "placeholder-hint" }, "[Телефон]"), " и другие — заполните сами. Ваши личные данные мы в нейросеть не передаём.")),
    letters.length
      ? letters.map(letterCard)
      : el("p", { class: "muted" }, "Писем пока нет."),
  );
}

function letterCard(letter) {
  const full = `Тема: ${letter.subject}\n\n${letter.body}`;
  const copy = button("Копировать", { variant: "soft", size: "sm", iconName: "copy" });
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(full);
      toast("Письмо скопировано", "success");
    } catch {
      toast("Не удалось скопировать — выделите текст вручную", "error");
    }
  });
  const download = button("Скачать .txt", { variant: "ghost", size: "sm", iconName: "download" });
  download.addEventListener("click", () => act(download, async () => {
    const text = await api.letterText(letter.id);
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const link = el("a", { href: url, download: `zapros-kp-${letter.id}.txt` });
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }));

  return el("article", { class: "letter" },
    el("div", { class: "row between" },
      el("div", {},
        el("div", { class: "strong" }, supplierName(letter.supplier_id)),
        el("div", { class: "small muted" }, letter.subject),
      ),
      el("div", { class: "row" }, copy, download),
    ),
    el("details", {},
      el("summary", { style: { marginTop: "10px" } }, "Показать письмо"),
      el("pre", { class: "letter-body" }, highlightPlaceholders(letter.body)),
    ),
  );
}
