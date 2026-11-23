// The platform's own list separator colour, where it has one. Web and Android have none, so callers fall
// back to the equivalent literal; iOS supplies the system colour in separatorColor.native.js.
export function systemSeparatorColor() {
  return null;
}

// The platform's chip fill (iOS: the system tertiary fill), where it has one.
export function systemFillColor() {
  return null;
}
