#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  printf 'Usage: %s TARGET.png RENDER.png REPORT.json DIFF.png\n' "$0" >&2
  exit 2
fi

target_path="$(realpath "$1")"
render_path="$(realpath "$2")"
report_path="$(realpath -m "$3")"
diff_path="$(realpath -m "$4")"

TARGET_PATH="$target_path" RENDER_PATH="$render_path" REPORT_PATH="$report_path" DIFF_PATH="$diff_path" \
  uv run --with pillow==12.1.0 python - <<'PY'
from __future__ import annotations

import json
import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageStat


def rmse_similarity(left: Image.Image, right: Image.Image) -> float:
    difference = ImageChops.difference(left, right)
    squares = ImageStat.Stat(difference).rms
    rmse = math.sqrt(sum(channel * channel for channel in squares) / len(squares))
    return max(0.0, 1.0 - rmse / 255.0)


target_path = Path(os.environ["TARGET_PATH"])
render_path = Path(os.environ["RENDER_PATH"])
report_path = Path(os.environ["REPORT_PATH"])
diff_path = Path(os.environ["DIFF_PATH"])
target = Image.open(target_path).convert("RGB")
render = Image.open(render_path).convert("RGB")
normalized_target = target.resize(render.size, Image.Resampling.LANCZOS)
macro_size = (256, max(1, round(256 * render.height / render.width)))
macro_target = normalized_target.resize(macro_size, Image.Resampling.LANCZOS)
macro_render = render.resize(macro_size, Image.Resampling.LANCZOS)
macro_similarity = rmse_similarity(macro_target, macro_render)
luminance_similarity = rmse_similarity(normalized_target.convert("L"), render.convert("L"))
target_histogram = normalized_target.resize((64, 64), Image.Resampling.LANCZOS).histogram()
render_histogram = render.resize((64, 64), Image.Resampling.LANCZOS).histogram()
histogram_distance = sum(abs(left - right) for left, right in zip(target_histogram, render_histogram, strict=True))
histogram_similarity = max(0.0, 1.0 - histogram_distance / (2.0 * 64.0 * 64.0 * 3.0))
composite = 0.55 * macro_similarity + 0.30 * luminance_similarity + 0.15 * histogram_similarity

raw_diff = ImageChops.difference(normalized_target, render)
amplified = ImageEnhance.Contrast(raw_diff).enhance(2.2)
diff_path.parent.mkdir(parents=True, exist_ok=True)
amplified.save(diff_path)
report = {
    "target": str(target_path),
    "render": str(render_path),
    "target_original_size": list(target.size),
    "render_size": list(render.size),
    "preprocessing": {
        "target_resize": "Lanczos to render dimensions",
        "color_mode": "RGB",
        "alpha": "discarded against decoded image background",
        "dpr": 1,
        "ignored_regions": [],
        "macro_size": list(macro_size)
    },
    "metric": "0.55 macro RGB RMSE + 0.30 full luminance RMSE + 0.15 normalized RGB histogram",
    "target_percent": 96.0,
    "macro_rgb_percent": round(macro_similarity * 100.0, 4),
    "luminance_percent": round(luminance_similarity * 100.0, 4),
    "histogram_percent": round(histogram_similarity * 100.0, 4),
    "composite_percent": round(composite * 100.0, 4),
    "passes_target": composite > 0.96,
    "diff": str(diff_path)
}
report_path.parent.mkdir(parents=True, exist_ok=True)
report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2, sort_keys=True))
PY
