// Маскот FoodFinder — морковка. Рисуется inline-SVG, чтобы анимировать части
// (ботва качается, глаза моргают) и менять настроение.
//   mood: "happy" | "thinking" | "sad" | "wink"
//   wave: машет ручкой (для приветствий)

let uid = 0;

const FACES = {
  happy: `
    <g class="m-eyes">
      <ellipse cx="48" cy="70" rx="5" ry="6.5" fill="#2b2420"/>
      <ellipse cx="72" cy="70" rx="5" ry="6.5" fill="#2b2420"/>
      <circle cx="49.8" cy="67.4" r="1.9" fill="#fff"/>
      <circle cx="73.8" cy="67.4" r="1.9" fill="#fff"/>
    </g>
    <path d="M51 82 Q60 92 69 82" stroke="#2b2420" stroke-width="3" fill="none" stroke-linecap="round"/>
    <path d="M55 85.5 Q60 89.5 65 85.5 Q60 92 55 85.5Z" fill="#e2574c"/>`,
  wink: `
    <path d="M43 70 Q48 65 53 70" stroke="#2b2420" stroke-width="3" fill="none" stroke-linecap="round"/>
    <g class="m-eyes">
      <ellipse cx="72" cy="70" rx="5" ry="6.5" fill="#2b2420"/>
      <circle cx="73.8" cy="67.4" r="1.9" fill="#fff"/>
    </g>
    <path d="M51 82 Q60 92 69 82" stroke="#2b2420" stroke-width="3" fill="none" stroke-linecap="round"/>`,
  thinking: `
    <g class="m-eyes">
      <ellipse cx="48" cy="69" rx="5" ry="6.5" fill="#2b2420"/>
      <ellipse cx="72" cy="69" rx="5" ry="6.5" fill="#2b2420"/>
      <circle cx="50.5" cy="65.5" r="2" fill="#fff"/>
      <circle cx="74.5" cy="65.5" r="2" fill="#fff"/>
    </g>
    <path d="M42 59 Q48 55 54 58" stroke="#2b2420" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <ellipse cx="61" cy="85" rx="4" ry="4.5" fill="#2b2420"/>`,
  sad: `
    <g class="m-eyes">
      <ellipse cx="48" cy="71" rx="5" ry="6" fill="#2b2420"/>
      <ellipse cx="72" cy="71" rx="5" ry="6" fill="#2b2420"/>
      <circle cx="49.6" cy="68.6" r="1.8" fill="#fff"/>
      <circle cx="73.6" cy="68.6" r="1.8" fill="#fff"/>
    </g>
    <path d="M41 61 Q47 58 53 62" stroke="#2b2420" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <path d="M79 61 Q73 58 67 62" stroke="#2b2420" stroke-width="2.4" fill="none" stroke-linecap="round"/>
    <path d="M52 88 Q60 81 68 88" stroke="#2b2420" stroke-width="3" fill="none" stroke-linecap="round"/>`,
};

export function mascotSvg({ mood = "happy", wave = false } = {}) {
  const id = `carrot-${++uid}`;
  const face = FACES[mood] || FACES.happy;
  const arms = wave
    ? `<path d="M31 92 Q22 96 17 106" stroke="#e5731d" stroke-width="5" fill="none" stroke-linecap="round"/>
       <g class="m-wave"><path d="M89 88 Q99 80 101 68" stroke="#e5731d" stroke-width="5" fill="none" stroke-linecap="round"/></g>`
    : "";
  return `
<svg class="mascot mascot-${mood}" viewBox="0 0 120 150" role="img" aria-label="Морковка — маскот FoodFinder">
  <defs>
    <linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#ffa851"/>
      <stop offset="1" stop-color="#f0761c"/>
    </linearGradient>
  </defs>
  <g class="m-body">
    <g class="m-leaves">
      <path d="M58 38 C44 32 35 20 37 9 C48 12 56 24 60 35Z" fill="#4ea75c"/>
      <path d="M62 38 C76 32 85 20 83 9 C72 12 64 24 60 35Z" fill="#4ea75c"/>
      <path d="M60 38 C53 24 55 10 61 2 C68 10 68 25 61 38Z" fill="#63c06b"/>
    </g>
    ${arms}
    <path d="M60 146 C50 146 30 101 27 69 C24 45 40 33 60 33 C80 33 96 45 93 69 C90 101 70 146 60 146Z" fill="url(#${id})"/>
    <path d="M41 46 C36 52 34 60 35 68" stroke="#ffd1a3" stroke-width="4" fill="none" stroke-linecap="round" opacity=".7"/>
    <g stroke="#d9661a" stroke-width="2.6" fill="none" stroke-linecap="round" opacity=".75">
      <path d="M35 98 q7 3 12 0"/>
      <path d="M85 108 q-7 3 -12 0"/>
      <path d="M48 126 q6 2 10 0"/>
    </g>
    <ellipse cx="39" cy="81" rx="6.5" ry="3.8" fill="#ff7a8a" opacity=".55"/>
    <ellipse cx="81" cy="81" rx="6.5" ry="3.8" fill="#ff7a8a" opacity=".55"/>
    ${face}
  </g>
</svg>`;
}

// DOM-элемент с маскотом (SVG — наш собственный, innerHTML здесь безопасен)
export function mascot(options = {}) {
  const wrap = document.createElement("span");
  wrap.className = `mascot-wrap ${options.className || ""}`.trim();
  wrap.innerHTML = mascotSvg(options);
  return wrap.firstElementChild;
}
