from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError

from domain_checks.common_check import _is_browser_infra_error  # noqa: SLF001


@dataclass(frozen=True)
class WebVitalsResult:
    domain: str
    ok: bool
    metrics: dict[str, Any]
    error: str | None
    elapsed_ms: float | None
    browser_infra_error: bool


_VITALS_INIT_SCRIPT = r"""
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


async def measure_web_vitals(
    *,
    domain: str,
    url: str,
    browser: Browser,
    timeout_seconds: float = 45.0,
    post_load_wait_ms: int = 4500,
) -> WebVitalsResult:
    cleaned_domain = str(domain or "").strip().lower()
    target_url = str(url or "").strip()
    timeout_ms = int(max(1.0, float(timeout_seconds)) * 1000)

    started = time.perf_counter()
    context = None
    page = None
    browser_infra_error = False
    try:
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        try:
            await page.add_init_script(_VITALS_INIT_SCRIPT)
        except Exception:
            pass

        # Use full load for vitals (domcontentloaded is too early for LCP).
        await page.goto(target_url, wait_until="load", timeout=timeout_ms)
        await asyncio.sleep(max(0.0, int(post_load_wait_ms) / 1000.0))

        # Minimal interaction to surface some Event Timing entries for INP.
        try:
            await page.click("body", timeout=min(timeout_ms, 5000))
        except Exception:
            pass

        try:
            await page.evaluate("() => window.__pitchaiVitalsStop && window.__pitchaiVitalsStop()")
        except Exception:
            pass

        metrics = await page.evaluate(
            "() => {\n"
            "  const v = window.__pitchaiVitals || {};\n"
            "  const nav = performance.getEntriesByType('navigation')[0];\n"
            "  const fcp = performance.getEntriesByName('first-contentful-paint')[0];\n"
            "  return {\n"
            "    lcp_ms: (typeof v.lcp === 'number' ? v.lcp : null),\n"
            "    cls: (typeof v.cls === 'number' ? v.cls : null),\n"
            "    inp_ms: (typeof v.inpMax === 'number' ? v.inpMax : null),\n"
            "    ttfb_ms: (nav && typeof nav.responseStart === 'number' ? nav.responseStart : null),\n"
            "    fcp_ms: (fcp && typeof fcp.startTime === 'number' ? fcp.startTime : null),\n"
            "    dom_content_loaded_ms: (nav && typeof nav.domContentLoadedEventEnd === 'number' ? nav.domContentLoadedEventEnd : null),\n"
            "    load_ms: (nav && typeof nav.loadEventEnd === 'number' ? nav.loadEventEnd : null),\n"
            "    errors: (Array.isArray(v.errors) ? v.errors.slice(0, 10) : []),\n"
            "  };\n"
            "}\n"
        )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return WebVitalsResult(
            domain=cleaned_domain,
            ok=True,
            metrics=metrics if isinstance(metrics, dict) else {},
            error=None,
            elapsed_ms=round(elapsed_ms, 3),
            browser_infra_error=False,
        )
    except PlaywrightTimeoutError as exc:
        browser_infra_error = _is_browser_infra_error(exc)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return WebVitalsResult(
            domain=cleaned_domain,
            ok=False,
            metrics={},
            error=f"TimeoutError: {exc}",
            elapsed_ms=round(elapsed_ms, 3),
            browser_infra_error=browser_infra_error,
        )
    except PlaywrightError as exc:
        browser_infra_error = _is_browser_infra_error(exc)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return WebVitalsResult(
            domain=cleaned_domain,
            ok=False,
            metrics={},
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=round(elapsed_ms, 3),
            browser_infra_error=browser_infra_error,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return WebVitalsResult(
            domain=cleaned_domain,
            ok=False,
            metrics={},
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=round(elapsed_ms, 3),
            browser_infra_error=False,
        )
    finally:
        if page is not None:
            try:
                await page.close()
            except Exception:
                pass
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass

