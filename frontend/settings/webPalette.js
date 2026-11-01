const token = (name) => `var(--settings-card-${name})`;
export const webPalette = Object.fromEntries([
  ['text', 'text'], ['border', 'border'], ['background', 'background'],
  ['badgeBorder', 'badge-border'], ['badgeBackground', 'badge-background'],
  ['badgeText', 'badge-text'], ['badgeHover', 'badge-hover'], ['focus', 'focus'],
].map(([key, name]) => [key, token(name)]));
webPalette.fontFamily = 'inherit';
webPalette.interactiveStyle = {
  cursor: 'pointer', textDecorationLine: 'none',
  transitionProperty: 'background-color, border-color, color, box-shadow',
};
// Browser focus indication uses :focus-visible, so pointer clicks do not leave a ring.
