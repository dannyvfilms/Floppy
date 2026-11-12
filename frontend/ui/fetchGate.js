// Runs at most `limit` async tasks at once; the rest wait their turn in order.
export function createFetchGate(limit) {
  let active = 0;
  const waiting = [];
  const release = () => {
    active -= 1;
    const next = waiting.shift();
    if (next) next();
  };
  return async function run(task) {
    if (active >= limit) await new Promise(resolve => waiting.push(resolve));
    active += 1;
    try {
      return await task();
    } finally {
      release();
    }
  };
}
