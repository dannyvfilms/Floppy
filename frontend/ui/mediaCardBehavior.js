// `clickable` mirrors clickable_media_cards: when true, touch input opens the
// card directly instead of using the first tap to reveal hover actions.
export function shouldRevealMediaCardActions(actions, revealed) {
  return Boolean(actions?.items?.length && !actions.clickable && !revealed);
}
