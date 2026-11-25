// The press-and-hold menu of the media card is a platform control (a system menu on iOS, a Material
// menu on Android), so the shared card calls whichever one the app installed, the way Icon calls the
// installed icon renderer. With none installed (the browser) the card has no press-and-hold menu.
let installed = null;

export function setCardMenu(component) {
  installed = component;
}

export function getCardMenu() {
  return installed;
}
