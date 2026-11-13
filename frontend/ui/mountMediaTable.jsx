// The release web media table is the server-rendered <table> with its Alpine
// column controls. Mounting the shared React Native table on top of it changed
// column widths and row heights after first paint, which the user sees as the
// whole media list re-laying-out. Until the web page composition can render one
// table from the same page model, keep the release table and use the shared
// React Native table on native only.
//
// This adapter deliberately leaves the server table in place. The fallback
// already carries sorting, column configuration and horizontal scrolling.
export function mountMediaTable() {
  return () => {};
}
