#!/usr/bin/env bash
# Render the finished Markdown with pinned, isolated command-line tools.
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo 'Usage: bash render_reports.sh NEW_OUTPUT_DIRECTORY' >&2
    exit 2
fi
report_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
report_output=$1
mkdir -- "$report_output"
report_output=$(cd -- "$report_output" && pwd)
render_tmp=$(mktemp -d -- "$report_output/.render-XXXXXXXX")
trap 'rm -rf -- "$render_tmp"' EXIT

for report_name in dossier executive-report; do
    uvx --python 3.12.12 --from Markdown==3.9 markdown_py \
        --encoding utf-8 --extension tables --extension fenced_code --extension toc \
        --file "$render_tmp/$report_name.html" "$report_root/$report_name.md"
    uvx --python 3.12.12 --from weasyprint==66.0 weasyprint \
        --encoding utf-8 --base-url "$report_root/" --stylesheet "$report_root/report.css" \
        "$render_tmp/$report_name.html" "$report_output/$report_name.pdf"
done
