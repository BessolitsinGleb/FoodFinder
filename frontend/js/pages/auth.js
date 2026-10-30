// Вход, регистрация и подтверждение почты кодом.
import { api, session } from "../api.js";
import { icon } from "../icons.js";
import { field, loadProfile, regionSelect, renderFooter, renderHeader, showFieldErrors } from "../layout.js";
import { mascot } from "../mascot.js";
import { $, button, el, mount, toast, withLoading } from "../utils.js";

const params = new URLSearchParams(location.search);
// Возвращаемся туда, откуда пришли, но только на свои страницы
const next = /^[\w-]+\.html(\?[\w=&%-]*)?$/.test(params.get("next") || "") ? params.get("next") : "orders.html";

if (session.token) location.replace(next);

renderHeader({ authed: false });
renderFooter();

const card = $("#auth-card");
const PENDING_EMAIL = "ff_pending_email";
const RESEND_AT = "ff_resend_at";

const state = {
  mode: sessionStorage.getItem(PENDING_EMAIL) ? "verify" : params.get("mode") === "register" ? "register" : "login",
  email: sessionStorage.getItem(PENDING_EMAIL) || "",
};

function go(mode, email = state.email) {
  state.mode = mode;
  state.email = email;
  if (mode === "verify") sessionStorage.setItem(PENDING_EMAIL, email);
  else sessionStorage.removeItem(PENDING_EMAIL);
  render();
}

async function finishLogin(token) {
  session.set(token);
  sessionStorage.removeItem(PENDING_EMAIL);
  sessionStorage.removeItem(RESEND_AT);
  try {
    await loadProfile();
  } catch {
    // профиль подгрузится на следующей странице
  }
  location.replace(next);
}

function alertBox(type = "danger") {
  return el("div", { class: `alert alert-${type}`, hidden: true, role: "alert" });
}

function showAlert(box, message, type = "danger") {
  box.className = `alert alert-${type}`;
  mount(box, icon(type === "danger" ? "alert" : "info"), el("div", {}, message));
  box.hidden = false;
}

// ---------- Вход ----------

function loginForm() {
  const email = el("input", { class: "input", type: "email", name: "email", id: "email", autocomplete: "email", required: true, value: state.email });
  const password = el("input", { class: "input", type: "password", name: "password", id: "password", autocomplete: "current-password", required: true });
  const alert = alertBox();
  const submit = button("Войти", { variant: "primary", size: "lg", type: "submit", class: "btn-block" });

  const form = el("form", { novalidate: true },
    field("Email", email),
    field("Пароль", password),
    alert,
    submit,
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    alert.hidden = true;
    if (!email.value || !password.value) {
      showAlert(alert, "Введите email и пароль");
      return;
    }
    withLoading(submit, async () => {
      try {
        const { access_token } = await api.login(email.value.trim(), password.value);
        await finishLogin(access_token);
      } catch (err) {
        if (err.status === 403) {
          // Почта не подтверждена — сразу ведём на ввод кода
          go("verify", email.value.trim().toLowerCase());
          toast("Почта ещё не подтверждена — введите код из письма или запросите новый");
        } else {
          showAlert(alert, err.message);
        }
      }
    });
  });
  setTimeout(() => (email.value ? password : email).focus());
  return form;
}

// ---------- Регистрация ----------

async function registerForm() {
  const name = el("input", { class: "input", name: "name", id: "name", autocomplete: "name", required: true, maxlength: 100 });
  const email = el("input", { class: "input", type: "email", name: "email", id: "email", autocomplete: "email", required: true });
  const password = el("input", { class: "input", type: "password", name: "password", id: "password", autocomplete: "new-password", required: true, minlength: 8 });
  const city = el("input", { class: "input", name: "city", id: "city", autocomplete: "address-level2", required: true, placeholder: "Например, Казань" });
  const region = await regionSelect();
  const alert = alertBox();
  const submit = button("Создать аккаунт", { variant: "primary", size: "lg", type: "submit", class: "btn-block" });

  const form = el("form", { novalidate: true },
    el("div", { class: "form-grid" },
      el("div", { class: "span-2" }, field("Как вас зовут", name)),
      el("div", { class: "span-2" }, field("Email", email, { hint: "Пришлём на него код подтверждения" })),
      el("div", { class: "span-2" }, field("Пароль", password, { hint: "Минимум 8 символов" })),
      field("Город", city),
      field("Регион", region),
    ),
    el("p", { class: "tiny faint" }, "С города и региона начнём поиск поставщиков. Изменить можно в профиле."),
    alert,
    submit,
  );

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    alert.hidden = true;
    const local = {};
    if (!name.value.trim()) local.name = "заполните поле";
    if (!email.value.includes("@")) local.email = "некорректный email";
    if (password.value.length < 8) local.password = "минимум 8 символов";
    if (!city.value.trim()) local.city = "заполните поле";
    if (!region.value) local.region = "выберите регион";
    showFieldErrors(form, local);
    if (Object.keys(local).length) return;

    withLoading(submit, async () => {
      const data = { name: name.value.trim(), email: email.value.trim(), password: password.value, city: city.value.trim(), region: region.value };
      try {
        await api.register(data);
        sessionStorage.setItem(RESEND_AT, String(Date.now() + 60_000));
        toast("Код отправлен на почту", "success");
        go("verify", data.email.toLowerCase());
      } catch (err) {
        showFieldErrors(form, err.fields);
        if (err.status === 409 && err.message.includes("не подтверждён")) {
          // Регистрация уже есть, но почта не подтверждена — предлагаем ввести код
          showAlert(alert, "Этот email уже зарегистрирован, но не подтверждён. Введите код из письма.", "warning");
          alert.append(button("Ввести код", { variant: "soft", size: "sm", onclick: () => go("verify", data.email.toLowerCase()) }));
        } else if (!Object.keys(err.fields).length) {
          showAlert(alert, err.message);
        }
      }
    });
  });
  setTimeout(() => name.focus());
  return form;
}

// ---------- Подтверждение почты ----------

function codeInputs(onComplete) {
  const wrap = el("div", { class: "code-inputs", role: "group", "aria-label": "Код из письма" });
  const inputs = Array.from({ length: 6 }, (_, i) =>
    el("input", {
      inputmode: "numeric",
      autocomplete: i === 0 ? "one-time-code" : "off",
      maxlength: 6,
      "aria-label": `Цифра ${i + 1} из 6`,
    }),
  );
  const value = () => inputs.map((input) => input.value).join("");
  const fill = (digits, from = 0) => {
    digits.split("").forEach((d, j) => inputs[from + j] && (inputs[from + j].value = d));
    inputs[Math.min(from + digits.length, 5)].focus();
  };
  const check = () => {
    wrap.classList.remove("invalid");
    if (value().length === 6) onComplete(value());
  };

  inputs.forEach((input, i) => {
    input.addEventListener("input", () => {
      const digits = input.value.replace(/\D/g, "");
      input.value = "";
      // Автозаполнение с телефона кладёт весь код в первое поле — раскладываем
      if (digits.length > 1) fill(digits.slice(0, 6 - i), i);
      else if (digits) {
        input.value = digits;
        if (i < 5) inputs[i + 1].focus();
      }
      check();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Backspace" && !input.value && i > 0) {
        inputs[i - 1].value = "";
        inputs[i - 1].focus();
        e.preventDefault();
      } else if (e.key === "ArrowLeft" && i > 0) inputs[i - 1].focus();
      else if (e.key === "ArrowRight" && i < 5) inputs[i + 1].focus();
    });
    input.addEventListener("paste", (e) => {
      const digits = (e.clipboardData?.getData("text") || "").replace(/\D/g, "").slice(0, 6);
      if (!digits) return;
      e.preventDefault();
      fill(digits);
      check();
    });
  });
  wrap.append(...inputs);
  return {
    wrap,
    value,
    focus: () => inputs[0].focus(),
    reset() {
      inputs.forEach((input) => (input.value = ""));
      inputs[0].focus();
    },
    shake() {
      wrap.classList.remove("invalid");
      void wrap.offsetWidth; // перезапуск анимации
      wrap.classList.add("invalid");
    },
  };
}

function verifyForm() {
  const alert = alertBox();
  const submit = button("Подтвердить", { variant: "primary", size: "lg", type: "submit", class: "btn-block" });
  const resend = button("Отправить код ещё раз", { variant: "ghost", size: "sm", iconName: "refresh" });
  let busy = false;

  const code = codeInputs(() => form.requestSubmit());

  // Обратный отсчёт до повторной отправки
  let timer = null;
  const tick = () => {
    const left = Math.ceil((Number(sessionStorage.getItem(RESEND_AT) || 0) - Date.now()) / 1000);
    resend.disabled = left > 0;
    mount(resend, icon("refresh"), left > 0 ? `Новый код через ${left} с` : "Отправить код ещё раз");
    if (left <= 0 && timer) {
      clearInterval(timer);
      timer = null;
    }
  };
  const startCooldown = (seconds) => {
    sessionStorage.setItem(RESEND_AT, String(Date.now() + seconds * 1000));
    if (!timer) timer = setInterval(tick, 1000);
    tick();
  };
  if (Number(sessionStorage.getItem(RESEND_AT) || 0) > Date.now()) timer = setInterval(tick, 1000);
  tick();

  resend.addEventListener("click", () =>
    withLoading(resend, async () => {
      alert.hidden = true;
      try {
        await api.resendCode(state.email);
        toast("Новый код отправлен. Старый больше не действует", "success");
        startCooldown(60);
        code.reset();
      } catch (err) {
        if (err.status === 429) {
          const seconds = Number(err.message.match(/(\d+)\s*сек/)?.[1] || 60);
          startCooldown(seconds);
        } else if (err.status === 409) {
          showAlert(alert, "Почта уже подтверждена — просто войдите.", "info");
        } else {
          showAlert(alert, err.message);
        }
      }
    }).finally(tick),
  );

  const form = el("form", { novalidate: true },
    code.wrap,
    alert,
    submit,
    el("div", { class: "row between" },
      resend,
      button("Другой email", { variant: "ghost", size: "sm", onclick: () => go("register", "") }),
    ),
  );

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) return;
    alert.hidden = true;
    if (code.value().length !== 6) {
      showAlert(alert, "Введите все 6 цифр из письма");
      code.shake();
      return;
    }
    busy = true;
    withLoading(submit, async () => {
      try {
        const { access_token } = await api.verifyEmail(state.email, code.value());
        toast("Почта подтверждена. Добро пожаловать!", "success");
        await finishLogin(access_token);
      } catch (err) {
        code.shake();
        code.reset();
        // Каждую ошибку бэкенда объясняем по-человечески
        if (err.status === 400) showAlert(alert, err.message);
        else if (err.status === 410) showAlert(alert, "Срок действия кода истёк. Запросите новый — кнопка ниже.", "warning");
        else if (err.status === 429) showAlert(alert, "Неверный код введён слишком много раз, этот код больше не действует. Запросите новый.", "warning");
        else if (err.status === 409) {
          showAlert(alert, "Почта уже подтверждена — войдите с паролем.", "info");
          setTimeout(() => go("login"), 1500);
        } else if (err.status === 404) showAlert(alert, "Аккаунт с таким email не найден. Зарегистрируйтесь заново.");
        else showAlert(alert, err.message);
      } finally {
        busy = false;
      }
    });
  });
  setTimeout(code.focus);
  return form;
}

// ---------- Отрисовка ----------

async function render() {
  const isVerify = state.mode === "verify";
  const titles = {
    login: ["С возвращением!", "Войдите, чтобы продолжить закупки"],
    register: ["Давайте знакомиться", "Аккаунт нужен, чтобы сохранять закупки и письма"],
    verify: ["Проверьте почту", null],
  };
  const [title, subtitle] = titles[state.mode];

  const tabs = isVerify
    ? null
    : el("div", { class: "tabs", role: "tablist" },
        ["login", "register"].map((mode) =>
          el("button", {
            type: "button",
            role: "tab",
            "aria-selected": String(state.mode === mode),
            onclick: () => state.mode !== mode && go(mode, ""),
          }, mode === "login" ? "Вход" : "Регистрация"),
        ),
      );

  const subtitleNode = isVerify
    ? el("p", { class: "subtitle" }, "Мы отправили 6-значный код на ", el("b", {}, state.email), ". Он действует 10 минут.")
    : el("p", { class: "subtitle" }, subtitle);

  mount(card,
    mascot({ mood: isVerify ? "wink" : "happy", wave: state.mode === "register" }),
    el("h1", {}, title),
    subtitleNode,
    tabs,
    el("div", { class: "page-loader", style: { padding: "30px 0" } }, el("div", { class: "spinner" })),
  );

  const form = state.mode === "login" ? loginForm() : state.mode === "register" ? await registerForm() : verifyForm();
  card.lastChild.replaceWith(form);
}

render().catch((err) => {
  mount(card, el("div", { class: "alert alert-danger" }, icon("alert"), err.message));
});
