// Общий каркас страниц: шапка, подвал, тема, проверка входа.
import { APP_NAME } from "./config.js";
import { api, getRegions, session } from "./api.js";
import { icon } from "./icons.js";
import { mascot } from "./mascot.js";
import { $, button, el, mount } from "./utils.js";

// ---------- Тема ----------

export function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("ff_theme", theme);
  } catch {}
}

function themeToggle() {
  const btn = el("button", { type: "button", class: "btn btn-ghost btn-icon theme-toggle" });
  const render = () => {
    const dark = currentTheme() === "dark";
    btn.setAttribute("aria-label", dark ? "Включить светлую тему" : "Включить тёмную тему");
    btn.title = btn.getAttribute("aria-label");
    mount(btn, icon(dark ? "sun" : "moon"));
  };
  btn.addEventListener("click", () => {
    setTheme(currentTheme() === "dark" ? "light" : "dark");
    render();
  });
  render();
  return btn;
}

// ---------- Шапка и подвал ----------

export function logo(href = "index.html") {
  const carrot = mascot();
  carrot.classList.add("still");
  return el("a", { class: "logo", href, "aria-label": `${APP_NAME} — на главную` }, carrot, el("span", {}, "Food", el("b", {}, "Finder")));
}

export function renderHeader({ active, authed = true } = {}) {
  let header = $("#app-header");
  if (!header) {
    header = el("header", { id: "app-header" });
    document.body.prepend(header);
  }
  header.className = "app-header";

  const nav = authed
    ? el("nav", { class: "nav", "aria-label": "Основное меню" },
        el("a", { href: "orders.html", class: active === "orders" ? "active" : null }, icon("box"), el("span", {}, "Мои закупки")),
        el("a", { href: "profile.html", class: active === "profile" ? "active" : null }, icon("user"), el("span", {}, "Профиль")),
      )
    : null;

  const actions = el("div", { class: "header-actions" },
    authed && session.profile ? el("span", { class: "header-user" }, session.profile.name) : null,
    themeToggle(),
    authed
      ? el("button", { type: "button", class: "btn btn-ghost btn-icon", "aria-label": "Выйти", title: "Выйти", onclick: logout }, icon("logout"))
      : null,
  );

  mount(header, el("div", { class: "container" }, logo(authed ? "orders.html" : "index.html"), nav, actions));
}

export function renderFooter() {
  let footer = $("#app-footer");
  if (!footer) {
    footer = el("footer", { id: "app-footer" });
    document.body.append(footer);
  }
  footer.className = "app-footer";
  mount(footer, el("div", { class: "container" },
    el("span", {}, `© ${new Date().getFullYear()} ${APP_NAME}`),
    el("span", {}, "Поставщики продуктов, сырья и упаковки рядом с вами"),
  ));
}

// ---------- Вход ----------

export function logout() {
  session.clear();
  location.href = "auth.html";
}

// Страница только для вошедших: без токена — на вход и обратно после него
export function requireAuth() {
  if (!session.token) {
    const next = encodeURIComponent(location.pathname.split("/").pop() + location.search);
    location.replace(`auth.html?next=${next}`);
    return false;
  }
  return true;
}

export async function loadProfile() {
  const user = await api.me();
  session.profile = user;
  const name = $(".header-user");
  if (name) name.textContent = user.name;
  return user;
}

// ---------- Общие виджеты ----------

// <select> с регионами, сгруппированными по федеральным округам
export async function regionSelect({ name = "region", value = "", required = true, id } = {}) {
  const select = el("select", { class: "select", name, id: id || name, required });
  select.append(el("option", { value: "", disabled: true, selected: !value }, "Выберите регион"));
  const regions = await getRegions();
  const byDistrict = new Map();
  for (const region of regions) {
    if (!byDistrict.has(region.federal_district)) byDistrict.set(region.federal_district, []);
    byDistrict.get(region.federal_district).push(region.name);
  }
  for (const [district, names] of [...byDistrict].sort(([a], [b]) => a.localeCompare(b, "ru"))) {
    select.append(el("optgroup", { label: `${district} ФО` },
      names.map((n) => el("option", { value: n, selected: n === value }, n))));
  }
  return select;
}

export function pageLoader(text = "Загружаем…") {
  return el("div", { class: "page-loader" }, mascot({ mood: "thinking" }), el("div", {}, text));
}

export function errorState(message, onRetry) {
  return el("div", { class: "empty" },
    mascot({ mood: "sad" }),
    el("h3", {}, "Не получилось загрузить"),
    el("p", {}, message),
    onRetry ? button("Попробовать ещё раз", { variant: "soft", iconName: "refresh", onclick: onRetry }) : null,
  );
}

// Поле формы с подписью и местом под ошибку
export function field(label, control, { hint, name } = {}) {
  const fieldName = name || control.name;
  return el("div", { class: "field", dataset: { field: fieldName } },
    el("label", { for: control.id || fieldName }, label),
    control,
    hint ? el("div", { class: "hint" }, hint) : null,
    el("div", { class: "error", hidden: true }),
  );
}

// Разложить ошибки валидации от API по полям формы
export function showFieldErrors(form, fields = {}) {
  form.querySelectorAll(".field").forEach((node) => {
    const message = fields[node.dataset.field];
    const error = node.querySelector(".error");
    const control = node.querySelector(".input, .select, .textarea");
    error.hidden = !message;
    error.textContent = message || "";
    control?.classList.toggle("invalid", Boolean(message));
  });
}
