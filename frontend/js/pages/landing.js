import { session } from "../api.js";
import { icon } from "../icons.js";
import { renderFooter, renderHeader } from "../layout.js";
import { mascot } from "../mascot.js";
import { $, el, mount } from "../utils.js";

renderHeader({ authed: false });
renderFooter();

$("#hero-art").append(mascot({ wave: true }));

const loggedIn = Boolean(session.token);
mount($("#hero-actions"),
  loggedIn
    ? el("a", { class: "btn btn-primary btn-lg", href: "orders.html" }, "Мои закупки")
    : [
        el("a", { class: "btn btn-primary btn-lg", href: "auth.html?mode=register" }, "Начать бесплатно"),
        el("a", { class: "btn btn-lg", href: "auth.html" }, "Войти"),
      ],
);

mount($("#trust-row"),
  el("span", {}, icon("shield"), "Оценка по формуле, а не «на глаз»"),
  el("span", {}, icon("pin"), "Сначала — поставщики рядом"),
);

const features = [
  ["pin", "Поиск рядом с вами", "Город, регион, федеральный округ, вся Россия — расширяем круг, пока не найдём достаточно вариантов."],
  ["shield", "Проверка и честная оценка", "Документы, отзывы, ИНН и возраст компании сводятся в рейтинг безопасности от 1 до 5. Видно, из чего он сложился."],
  ["file", "Письма в один клик", "Выберите поставщиков — получите письма-запросы КП. Ваши личные данные никуда не уходят: поля остаются пустыми."],
];
mount($("#features"), features.map(([iconName, title, text]) =>
  el("article", { class: "card feature" },
    el("div", { class: "feature-icon" }, icon(iconName)),
    el("h3", {}, title),
    el("p", {}, text),
  ),
));
