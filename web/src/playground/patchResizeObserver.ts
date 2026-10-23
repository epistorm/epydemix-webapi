// Recharts' ResponsiveContainer (and other observers) can fire a synchronous
// "ResizeObserver loop completed with undelivered notifications" warning that
// webpack-dev-server's overlay treats as a fatal runtime error. Wrapping the
// observer callback in requestAnimationFrame defers it past the current frame,
// breaking the loop at its source.
//
// Apply once at module load (idempotent via a flag on window).

declare global {
  interface Window {
    __resizeObserverPatched?: boolean;
  }
}

if (typeof window !== 'undefined' && !window.__resizeObserverPatched && window.ResizeObserver) {
  window.__resizeObserverPatched = true;
  const Original = window.ResizeObserver;
  window.ResizeObserver = class PatchedResizeObserver extends Original {
    constructor(callback: ResizeObserverCallback) {
      super((entries, observer) => {
        window.requestAnimationFrame(() => {
          try {
            callback(entries, observer);
          } catch {
            // Swallow callback errors so a single broken observer doesn't
            // poison the rest of the page.
          }
        });
      });
    }
  };
}

export {};
