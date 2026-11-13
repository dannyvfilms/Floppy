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

// Under the trigger with right edges aligned; when that would push the menu past the left edge of the
// screen (a trigger near the left), its left edge aligns with the trigger instead and is kept on screen.
// Flips above the trigger when there is no room below.
export function dropdownPlacement(anchor, bounds, estimatedHeight = 112, width = DROPDOWN.width) {
  const x = anchor.x - bounds.x;
  const y = anchor.y - bounds.y;
  const triggerRight = x + anchor.width;
  const horizontal = triggerRight - width >= 8
    ? { right: Math.max(8, bounds.width - triggerRight) }
    : { left: Math.min(Math.max(8, x), Math.max(8, bounds.width - width - 8)) };
  const below = y + anchor.height + 4;
  return below + Math.min(estimatedHeight, bounds.height - 16) > bounds.height - 8
    ? { ...horizontal, bottom: Math.max(8, bounds.height - y + 4) }
    : { ...horizontal, top: below };
}
