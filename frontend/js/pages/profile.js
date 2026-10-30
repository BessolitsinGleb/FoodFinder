// Профиль: имя, город и регион (с них начинается поиск), тема, удаление аккаунта.
import { api, session } from "../api.js";
import { icon } from "../icons.js";
import {
  currentTheme, errorState, field, loadProfile, logout, pageLoader, regionSelect, renderFooter, renderHeader,
  requireAuth, showFieldErrors,
} from "../layout.js";
import { mascot } from "../mascot.js";
import { $, button, confirmDialog, el, formatDate, mount, toast, withLoading } from "../utils.js";

const page = $("#page");

if (requireAuth()) {
  renderHeader({ active: "profile" });
  renderFooter();
  start();
}

async function start() {
  mount(page, pageLoader());
  try {
    const user = await loadProfile();
    render(user, await regionSelect({ value: user.region }));
  } catch (err) {
    mount(page, errorState(err.message, start));
  }
}

function render(user, region) {
  const name = el("input", { class: "input", name: "name", id: "name", value: user.name, maxlength: 100, required: true, autocomplete: "name" });
  const email = el("input", { class: "input", name: "email", id: "email", value: user.email, disabled: true });
  const city = el("input", { class: "input", name: "city", id: "city", value: user.city, maxlength: 100, required: true });
  const save = button("Сохранить", { variant: "primary", type: "submit", iconName: "check" });

  const form = el("form", { class: "card", novalidate: true },
    el("div", { class: "card-title" }, el("h2", {}, "Личные данные")),
    el("div", { class: "form-grid" },
      el("div", { class: "span-2" }, field("Имя", name)),
      el("div", { class: "span-2" }, field("Email", email, { hint: "Email изменить нельзя — он подтверждён кодом" })),
      field("Город", city),
      field("Регион", region),
    ),
    el("p", { class: "small muted", style: { margin: "14px 0" } },
      "Город и регион подставляются в новые закупки как адрес доставки — с них начинается поиск поставщиков."),
    el("div", { class: "row end" }, save),
  );

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const data = { name: name.value.trim(), city: city.value.trim(), region: region.value };
    const local = {};
    if (!data.name) local.name = "заполните поле";
    if (!data.city) local.city = "заполните поле";
    showFieldErrors(form, local);
    if (Object.keys(local).length) return;
    withLoading(save, async () => {
      try {
        const updated = await api.updateMe(data);
        session.profile = updated;
        $(".header-user") && ($(".header-user").textContent = updated.name);
        showFieldErrors(form, {});
        toast("Профиль сохранён", "success");
      } catch (err) {
        showFieldErrors(form, err.fields);
        toast(err.message, "error");
      }
    });
  });

  const themeSwitch = el("div", { class: "segmented", role: "group", "aria-label": "Тема оформления" },
    [["light", "Светлая", "sun"], ["dark", "Тёмная", "moon"]].map(([value, label, iconName]) =>
      el("button", {
        type: "button",
        "aria-pressed": String(currentTheme() === value),
        style: { padding: "0 16px", display: "inline-flex", alignItems: "center", gap: "6px" },
        onclick: () => {
          document.documentElement.dataset.theme = value;
          try {
            localStorage.setItem("ff_theme", value);
          } catch {}
          render(user, region);
          renderHeader({ active: "profile" });
        },
      }, icon(iconName), label),
    ),
  );

  const remove = button("Удалить аккаунт", { variant: "danger", iconName: "trash" });
  remove.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: "Удалить аккаунт?",
      text: "Удалятся все закупки, подборки и письма. Отменить это нельзя.",
      confirmLabel: "Удалить навсегда",
      danger: true,
    });
    if (!ok) return;
    withLoading(remove, async () => {
      try {
        await api.deleteMe();
        session.clear();
        location.href = "index.html";
      } catch (err) {
        toast(err.message, "error");
      }
    });
  });

  mount(page,
    el("div", { class: "page-head" },
      el("div", {}, el("h1", {}, "Профиль"), el("p", {}, `С нами с ${formatDate(user.created_at)}`)),
    ),
    el("div", { class: "profile-grid" },
      form,
      el("div", { class: "stack" },
        el("div", { class: "card card-tight center profile-avatar" },
          mascot({ mood: "wink" }),
          el("p", { class: "strong", style: { margin: "8px 0 2px" } }, user.name),
          el("p", { class: "small muted", style: { margin: 0 } }, `${user.city}, ${user.region}`),
        ),
        el("div", { class: "card card-tight" },
          el("h3", {}, "Оформление"),
          themeSwitch,
        ),
        el("div", { class: "card card-tight" },
          button("Выйти из аккаунта", { variant: "ghost", iconName: "logout", class: "btn-block", onclick: logout }),
        ),
        el("div", { class: "card card-tight danger-zone" },
          el("h3", {}, "Опасная зона"),
          el("p", { class: "small muted" }, "Аккаунт и все данные удалятся без возможности восстановления."),
          remove,
        ),
      ),
    ),
  );
}
