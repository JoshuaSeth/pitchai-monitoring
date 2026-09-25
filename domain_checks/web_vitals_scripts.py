# Copyright (c) 2026 PitchAI. All rights reserved.
"""Browser scripts used to collect web-vitals measurements."""

VITALS_INIT_SCRIPT = r"""
(() => {
  try {
    window.__pitchaiVitals = {
      lcp: null,
      cls: 0,
      inpMax: null,
      errors: [],
    };

    try {
      const lcpObs = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const last = entries && entries.length ? entries[entries.length - 1] : null;
        if (last && typeof last.startTime === 'number') {
          window.__pitchaiVitals.lcp = last.startTime;
        }
      });
      lcpObs.observe({ type: 'largest-contentful-paint', buffered: true });
      window.__pitchaiVitals.__lcpObs = lcpObs;
    } catch (e) {
      window.__pitchaiVitals.errors.push('lcp:' + (e && e.message ? e.message : String(e)));
    }

    try {
      const clsObs = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry || entry.hadRecentInput) continue;
          const v = entry.value;
          if (typeof v === 'number') window.__pitchaiVitals.cls += v;
        }
      });
      clsObs.observe({ type: 'layout-shift', buffered: true });
      window.__pitchaiVitals.__clsObs = clsObs;
    } catch (e) {
      window.__pitchaiVitals.errors.push('cls:' + (e && e.message ? e.message : String(e)));
    }

    // INP approximation: capture max Event Timing duration for interactionId-backed events.
    try {
      const evtObs = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (!entry) continue;
          const iid = entry.interactionId || 0;
          if (!iid) continue;
          const d = entry.duration;
          if (typeof d !== 'number') continue;
          const prev = window.__pitchaiVitals.inpMax || 0;
          if (d > prev) window.__pitchaiVitals.inpMax = d;
        }
      });
      evtObs.observe({ type: 'event', buffered: true, durationThreshold: 0 });
      window.__pitchaiVitals.__evtObs = evtObs;
    } catch (e) {
      window.__pitchaiVitals.errors.push('inp:' + (e && e.message ? e.message : String(e)));
    }

    window.__pitchaiVitalsStop = () => {
      try { window.__pitchaiVitals.__lcpObs && window.__pitchaiVitals.__lcpObs.disconnect(); } catch (e) {}
      try { window.__pitchaiVitals.__clsObs && window.__pitchaiVitals.__clsObs.disconnect(); } catch (e) {}
      try { window.__pitchaiVitals.__evtObs && window.__pitchaiVitals.__evtObs.disconnect(); } catch (e) {}
    };
  } catch (e) {
    // ignore
  }
})();
"""

READ_VITALS_SCRIPT = r"""
() => {
  const v = window.__pitchaiVitals || {};
  const nav = performance.getEntriesByType('navigation')[0];
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  return {
    lcp_ms: (typeof v.lcp === 'number' ? v.lcp : null),
    cls: (typeof v.cls === 'number' ? v.cls : null),
    inp_ms: (typeof v.inpMax === 'number' ? v.inpMax : null),
    ttfb_ms: (nav && typeof nav.responseStart === 'number' ? nav.responseStart : null),
    fcp_ms: (fcp && typeof fcp.startTime === 'number' ? fcp.startTime : null),
    dom_content_loaded_ms: (nav && typeof nav.domContentLoadedEventEnd === 'number'
      ? nav.domContentLoadedEventEnd : null),
    load_ms: (nav && typeof nav.loadEventEnd === 'number' ? nav.loadEventEnd : null),
    errors: (Array.isArray(v.errors) ? v.errors.slice(0, 10) : []),
  };
}
"""
