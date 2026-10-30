// Подключается в <head> обычным скриптом (не модулем), чтобы тема применилась
// до отрисовки и страница не "мигала" светлым фоном в тёмной теме.
(function () {
  var theme = null;
  try {
    theme = localStorage.getItem("ff_theme");
  } catch (e) {}
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.dataset.theme = theme;
})();
