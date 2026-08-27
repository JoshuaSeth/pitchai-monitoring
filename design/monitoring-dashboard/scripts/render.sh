#!/usr/bin/env bash
set -euo pipefail

workspace_root="$(git rev-parse --show-toplevel)"
design_root="$workspace_root/design/monitoring-dashboard"

if [[ "${DESIGN_REUSE_COMPILED_CSS:-0}" != "1" ]]; then
  npx --yes tailwindcss@3.4.17 \
    -c "$design_root/tailwind.config.cjs" \
    -i "$design_root/static/input.css" \
    -o "$design_root/static/tailwind.css" \
    --minify
fi
test -s "$design_root/static/tailwind.css"

if [[ -n "${DESIGN_PYTHON_BIN:-}" ]]; then
  python_command=("$DESIGN_PYTHON_BIN")
else
  python_command=(uv run --isolated --no-project --with jinja2==3.1.5 python)
fi

DESIGN_ROOT="$design_root" "${python_command[@]}" - <<'PY'
from __future__ import annotations

import json
import os
from importlib.metadata import version
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

if version("Jinja2") != "3.1.5":
    raise RuntimeError("monitoring design rendering requires Jinja2 3.1.5")

design_root = Path(os.environ["DESIGN_ROOT"])
fixture = json.loads((design_root / "fixtures/monitoring-scenarios.json").read_text(encoding="utf-8"))
environment = Environment(
    loader=FileSystemLoader(design_root / "templates"),
    autoescape=select_autoescape(("html", "xml")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
pages = (
    ("concept_01", "pages/concept-01-incidents.html", "concept-01-incidents.html", "Incident accordion"),
    ("concept_03", "pages/concept-03-infrastructure.html", "concept-03-infrastructure.html", "Infrastructure triage"),
    ("concept_04", "pages/concept-04-reliability.html", "concept-04-reliability.html", "Reliability analysis"),
)
output_dir = design_root / "renders"
output_dir.mkdir(parents=True, exist_ok=True)
for fixture_key, template_name, output_name, page_title in pages:
    rendered = environment.get_template(template_name).render(
        shared=fixture["shared"],
        scenario=fixture[fixture_key],
        page_title=f"PitchAI Monitoring — {page_title}",
    )
    (output_dir / output_name).write_text(rendered, encoding="utf-8")
PY

printf 'Rendered monitoring concepts in %s/renders\n' "$design_root"
