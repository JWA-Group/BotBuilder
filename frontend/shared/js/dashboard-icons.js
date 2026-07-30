/**
 * Hydrate dashboard menu cards with SVG icon badges.
 */
import { renderCardIcon, CARD_ICON_THEMES } from "./icons.js";

export function hydrateDashboardIcons(root) {
  const scope = root || document;
  scope.querySelectorAll(".menu-grid .menu-card[data-icon]").forEach(function (card) {
    const name = card.getAttribute("data-icon");
    if (!name) return;
    const html = renderCardIcon(name, CARD_ICON_THEMES[name]);
    if (!html) return;
    const old = card.querySelector(".icon, .menu-icon-badge");
    if (old) old.outerHTML = html;
    else card.insertAdjacentHTML("afterbegin", html);
  });
}

hydrateDashboardIcons(document);
