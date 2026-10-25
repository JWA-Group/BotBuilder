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

  webapps:
    '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 7h8"/><path d="M9 17h6"/><path d="M12 10v4"/><path d="M10 12h4"/>',

  // Channel Hub analytics widgets
  growth:
    '<path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>',
  hours:
    '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  tags:
    '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
  feed:
    '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  metrics:
    '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  warnings:
    '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  posts:
    '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
  moderation:
    '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/>',
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
  webapps: "menu-icon-theme-cyan",
  growth: "menu-icon-theme-emerald",
  hours: "menu-icon-theme-blue",
  tags: "menu-icon-theme-pink",
  feed: "menu-icon-theme-violet",
  metrics: "menu-icon-theme-amber",
  warnings: "menu-icon-theme-orange",
  posts: "menu-icon-theme-slate",
  moderation: "menu-icon-theme-cyan",
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
