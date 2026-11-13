// One size for the app's small option dropdowns (the sidebar row options and the
// Search media type menu), so they match on web and native. The sidebar row options
// set the size; change it here, not in each menu.
export const DROPDOWN = {
  width: 208,
  radius: 8,
  paddingVertical: 4,
  itemPaddingHorizontal: 12,
  itemPaddingVertical: 10,
  itemGap: 8,
  fontSize: 14,
};

export function toggleDropdownSelection(selected, value) {
  return selected.includes(value) ? selected.filter(entry => entry !== value) : [...selected, value];
}

export function dropdownPlacement(anchor, bounds, estimatedHeight = 112) {
  const x = anchor.x - bounds.x;
  const y = anchor.y - bounds.y;
  const right = Math.max(8, bounds.width - x - anchor.width);
  const below = y + anchor.height + 4;
  return below + Math.min(estimatedHeight, bounds.height - 16) > bounds.height - 8
    ? { right, bottom: Math.max(8, bounds.height - y + 4) }
    : { right, top: below };
}
