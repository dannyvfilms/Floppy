// `clickable` mirrors clickable_media_cards: when true, touch input opens the
// card directly instead of using the first tap to reveal hover actions.
export function shouldRevealMediaCardActions(actions, revealed) {
  return Boolean(actions?.items?.length && !actions.clickable && !revealed);
}

// Dormant lines are visible at rest; hover lines wait for card reveal.
export function shouldShowMediaCardLine(model, line, revealed) {
  return !model.hoverMetadata || revealed || Boolean(line?.dormant);
}

export function shouldShowMediaCardCorner(model, chip, revealed) {
  return !model.hoverMetadata || revealed || chip.kind !== 'runtime';
}
