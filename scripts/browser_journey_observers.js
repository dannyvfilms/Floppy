// Opt-in benchmark only; never loaded by production templates.
(() => {
  const supported = PerformanceObserver.supportedEntryTypes || [];
  const state = {supported, lcp: null, long_tasks: [], dropped_long_tasks: 0};
  const observers = [];
  const record = (type, entries) => {
    for (const entry of entries) {
      if (type === "largest-contentful-paint") {
        state.lcp = {start_ms: entry.startTime, render_ms: entry.renderTime,
          load_ms: entry.loadTime, size: entry.size};
      } else if (state.long_tasks.length < 10000) {
        state.long_tasks.push({start_ms: entry.startTime, duration_ms: entry.duration});
      } else {
        state.dropped_long_tasks++;
      }
    }
  };
  for (const type of ["largest-contentful-paint", "longtask"]) {
    if (supported.includes(type)) {
      const observer = new PerformanceObserver(list => record(type, list.getEntries()));
      observer.observe({type, buffered: true});
      observers.push({observer, type});
    }
  }
  window.__floppyBenchmark = () => {
    for (const {observer, type} of observers) record(type, observer.takeRecords());
    return {...state, observed_ms: performance.now()};
  };
})();
