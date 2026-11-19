// A server base path that does not reach the API (a proxy answering with its
// HTML page) comes back as a 200 string. Treat that as a failure so a screen
// shows its error and Retry instead of an empty state.
export function expectObject(payload, what = 'The server') {
  if (payload && typeof payload === 'object') return payload;
  throw new Error(`${what} did not return the expected data. Check the server address and try again.`);
}
