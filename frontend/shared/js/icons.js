/**
 * Lightweight zero-dependency SVG icons for BotBuilder dashboard.
 * Vanilla ES module — no npm / lucide / react.
 */

const SVG_ATTRS =
  'xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';

/** @type {Record<string, string>} */
const ICON_PATHS = {
  monitoring:
    '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',

  channel_manager:
    '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',

  post_editor:
    '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>',

  chatbots:
    '<rect width="18" height="12" x="3" y="8" rx="2"/><path d="M12 2v6"/><path d="M8 13h.01"/><path d="M16 13h.01"/>',

  templates:
    '<rect width="18" height="7" x="3" y="3" rx="1"/><rect width="9" height="7" x="3" y="14" rx="1"/><rect width="5" height="7" x="16" y="14" rx="1"/>',

  broadcasts:
    '<path d="m3 3 3 9-3 9 19-9Z"/><path d="M6 12h16"/>',

  bot_analytics:
    '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',

  component_master:
    '<path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l6 3.43a2 2 0 0 0 2.06 0l6-3.43a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L11 9.49a2 2 0 0 0-2.06 0l-6 3.43z"/><path d="m12 21.82-6-3.43"/><path d="m12 21.82 6-3.43"/><path d="m12 21.82v-6.86"/><path d="M12 2 2 7.72 12 13.44 22 7.72 12 2z"/>',

  plugins:
    '<path d="M15.39 4.39a1 1 0 0 0 1.68-.474 2.5 2.5 0 1 1 3.014 3.015 1 1 0 0 0-.474 1.68l1.581 1.581a2.5 2.5 0 1 1-3.014 3.015 1 1 0 0 0-1.68-.474l-1.581 1.581a2.5 2.5 0 1 1-3.015-3.014 1 1 0 0 0 .474-1.68l-1.581-1.581a2.5 2.5 0 1 1 3.014-3.015 1 1 0 0 0 1.68.474z"/>',

  database:
    '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',

  deploy:
    '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
};

/**
 * @param {string} name
 * @param {string} [customClass]
 * @returns {string} Inline SVG markup
 */
export function getIcon(name, customClass = "") {
  const paths = ICON_PATHS[name];
  if (!paths) return "";
  const cls = customClass ? ` class="${String(customClass).replace(/"/g, "")}"` : "";
  return `<svg ${SVG_ATTRS}${cls}>${paths}</svg>`;
}

/** Soft glass gradients per dashboard card (CSS custom properties friendly). */
export const CARD_ICON_THEMES = {
  monitoring: "menu-icon-theme-blue",
  channel_manager: "menu-icon-theme-violet",
  post_editor: "menu-icon-theme-sky",
  chatbots: "menu-icon-theme-emerald",
  templates: "menu-icon-theme-amber",
  broadcasts: "menu-icon-theme-orange",
  bot_analytics: "menu-icon-theme-cyan",
  component_master: "menu-icon-theme-purple",
  plugins: "menu-icon-theme-pink",
  database: "menu-icon-theme-slate",
  deploy: "menu-icon-theme-rose",
};

/**
 * Glassmorphism badge wrapper for dashboard menu cards.
 * Uses project CSS classes (no Tailwind / npm).
 * @param {string} iconName
 * @param {string} [themeClass]
 * @returns {string}
 */
export function renderCardIcon(iconName, themeClass) {
  const theme = themeClass || CARD_ICON_THEMES[iconName] || "menu-icon-theme-blue";
  const svgContent = getIcon(iconName, "menu-icon-svg");
  if (!svgContent) return "";
  return (
    `<div class="menu-icon-badge ${theme}" aria-hidden="true">` +
    svgContent +
    `</div>`
  );
}

export const ICON_NAMES = Object.keys(ICON_PATHS);

export default { getIcon, renderCardIcon, CARD_ICON_THEMES, ICON_NAMES };
