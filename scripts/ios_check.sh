#!/bin/sh
set -eu

project_scratch=".build/xcodegen/ios"
cleanup() {
    rm -rf -- ".build/xcodegen"
}
trap cleanup EXIT HUP INT TERM

if ! command -v xcodegen >/dev/null 2>&1; then
    echo "ERROR: xcodegen is required to generate the quality-check project" >&2
    exit 1
fi

cleanup
mkdir -p "$project_scratch"
cp -R ios/. "$project_scratch"/
rm -rf -- "$project_scratch/Generated" "$project_scratch/CodexStatus.xcodeproj"
xcodegen generate --spec "$project_scratch/project.yml" --project "$project_scratch"
./scripts/ios_check.py "$@"
