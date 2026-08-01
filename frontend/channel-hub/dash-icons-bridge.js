/**
 * Expose dashboard SVG icon helpers for classic (non-module) Channel Hub scripts.
 */
import { getIcon, renderCardIcon, CARD_ICON_THEMES } from "/shared/js/icons.js";

window.BBIcons = {
  getIcon: getIcon,
  renderCardIcon: renderCardIcon,
  CARD_ICON_THEMES: CARD_ICON_THEMES,
};
