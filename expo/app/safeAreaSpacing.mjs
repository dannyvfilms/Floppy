export function horizontalContentPadding(insets, minimum) {
  return {
    paddingLeft: Math.max(0, minimum - insets.left),
    paddingRight: Math.max(0, minimum - insets.right),
  };
}
