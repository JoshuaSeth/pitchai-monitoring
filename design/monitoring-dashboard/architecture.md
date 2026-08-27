# Monitoring dashboard design architecture

This design workspace turns the live monitoring evidence in
[`docs/monitoring-actionable-incidents-ui-inventory-2026-08-25.md`](../../docs/monitoring-actionable-incidents-ui-inventory-2026-08-25.md)
into reproducible Jinja2/Tailwind screens. It is design evidence, not an
alternate production runtime.

## Product decision

The production dashboard is an operator surface for Seth/ORI and the PitchAI
team. Its dominant job is to move from *something is red* to *what failed, when,
who owns it, what evidence is safe to expose, and what should I inspect next*.
The three added tabs therefore cover the other questions an incident responder
must answer without triggering more production work:

1. **Infrastructure** — is host or container pressure contributing?
2. **Reliability** — is this isolated or consuming a service-group error budget?
3. **Journeys** — which user-critical path is broken, stale, disabled, or never run?

All three consume retained monitor/E2E state. Missing and stale data remain
first-class states. Alert routing stays visible, especially the exact five
dashboard-only domains, but is not changed by these views.

## Selected concept strategies

- **Concept 01 — incident accordion:** selected for the compact disclosure
  pattern and one dominant expanded incident, including a production database
  dependency failure with redacted evidence.
- **Concept 03 — infrastructure operator console:** selected for its resource
  hierarchy, threshold context, and dense hotspot table.
- **Concept 04 — reliability analysis:** selected for its SLO/error-budget
  hierarchy and incident history rhythm.

The production implementation borrows structure and hierarchy from these
concepts while retaining the existing light PitchAI monitoring language. Dark
or speculative styling in a generated image is not copied blindly.

## Component hierarchy

```text
templates/
  layouts/base.html
  components/
    chrome.html       operator header and five-tab navigation
    primitives.html   status labels, metric cells, facts, and sparklines
    incidents.html    incident disclosure rows and evidence panel
    infrastructure.html
    reliability.html
  pages/
    concept-01-incidents.html
    concept-03-infrastructure.html
    concept-04-reliability.html
fixtures/
  monitoring-scenarios.json
static/
  input.css
  tailwind.css         generated, pinned Tailwind output
renders/               generated HTML
screenshots/           browser captures
comparisons/           diff images and JSON reports
scripts/
  render.sh
  capture.sh
  compare.sh
```

Templates never hardcode business rows. All realistic content is held in the
JSON fixture and passed through the renderer. Visually, the system uses only a
page canvas and one white work surface at a time; alignment, rules, and type do
most grouping work. A bordered detail pane is reserved for the active
inspection state.

## Fidelity metric

`scripts/compare.sh` performs deterministic DPR normalization, target resize,
and RGB conversion, then applies the same two-pixel Gaussian anti-alias
normalization to the complete target and render. That radius removes generated-
image color grain and browser-versus-model glyph rasterization differences
without cropping, masking, or moving any pixels. The primary score is:

```text
100% full-frame RGB mean-absolute similarity after symmetric 2px normalization
```

The target is **greater than 96.0%**. The report also retains unnormalized RGB
MAE, macro-layout RMSE, full-resolution luminance RMSE, and histogram diagnostics.
The script writes an unnormalized full-resolution amplified diff image so a
passing perceptual score cannot replace visual review. Generated-image text can
be internally inconsistent; any residual mismatch is documented rather than
hidden by masks or ignored regions.

The source targets must be the actual ChatGPT Pro concept images. A render may
not be compared with itself or promoted as a passing target. The concept log
records the authenticated ten-image session, final-generation timestamp,
required retention wait, all ten file hashes, and the completed selected
comparisons.

## Reproduction commands

From the repository root:

```sh
design/monitoring-dashboard/scripts/render.sh
design/monitoring-dashboard/scripts/capture.sh
design/monitoring-dashboard/scripts/compare.sh TARGET.png SCREENSHOT.png REPORT.json DIFF.png
```

The renderer pins Jinja2 and Tailwind CLI versions. The capture script uses the
installed Google Chrome through Playwright and a local static server; setting
`DESIGN_CDP_URL` reuses an already-running Chrome instead of launching another
browser. The comparison script pins Pillow. Supplying `DESIGN_PYTHON_BIN`
reuses an existing interpreter; otherwise both Python scripts create isolated,
project-independent `uv` environments so they cannot resynchronize the runtime
venv.
