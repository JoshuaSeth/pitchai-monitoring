#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
source_svg="${script_dir}/Design/CodexStatusIcon.svg"
destination_png="${script_dir}/Resources/Assets.xcassets/AppIcon.appiconset/CodexStatus-1024.png"
contents_json="${script_dir}/Resources/Assets.xcassets/AppIcon.appiconset/Contents.json"
project_yaml="${script_dir}/project.yml"
render_tmp="$(mktemp -d /tmp/codex-status-app-icon.XXXXXX)"

cleanup() {
  if [[ -n "${render_tmp:-}" && -d "${render_tmp}" && "${render_tmp}" == /tmp/codex-status-app-icon.* ]]; then
    rm -rf -- "${render_tmp}"
  fi
}
trap cleanup EXIT

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

target_contains() {
  local target="$1"
  local needle="$2"
  awk -v header="  ${target}:" -v needle="${needle}" '
    $0 == header { inside = 1; next }
    inside && $0 ~ /^  [[:alnum:]_]+:$/ { exit }
    inside && index($0, needle) { found = 1 }
    END { exit found ? 0 : 1 }
  ' "${project_yaml}"
}

validate_contract() {
  command -v identify >/dev/null 2>&1 || fail 'ImageMagick identify is required to validate the app icon PNG.'
  command -v jq >/dev/null 2>&1 || fail 'jq is required to validate the app icon asset catalog.'

  grep -Fq 'viewBox="0 0 1024 1024"' "${source_svg}" || fail 'Icon SVG must use the 1024x1024 view box.'
  local background
  background="$(grep -F 'fill="url(#background)"' "${source_svg}" | head -n 1)"
  [[ "${background}" == *'width="1024"'* && "${background}" == *'height="1024"'* ]] ||
    fail 'Icon SVG must contain a full-bleed background.'
  [[ "${background}" != *' rx='* && "${background}" != *' ry='* ]] ||
    fail 'Icon SVG must not bake a rounded mask into the master.'

  jq -e '
    .info == {"author": "xcode", "version": 1}
    and (.images | length == 2)
    and ([.images[] | {filename, idiom, platform, size}] | sort_by(.platform)) == [
      {"filename": "CodexStatus-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"},
      {"filename": "CodexStatus-1024.png", "idiom": "universal", "platform": "watchos", "size": "1024x1024"}
    ]
  ' "${contents_json}" >/dev/null || fail 'Asset catalog must assign the same master to iOS and watchOS.'

  target_contains CodexStatus 'path: Resources/Assets.xcassets' || fail 'iPhone target must compile the shared asset catalog.'
  target_contains CodexStatus 'ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon' || fail 'iPhone target must compile AppIcon.'
  target_contains CodexStatusWatch 'path: Resources/Assets.xcassets' || fail 'Watch target must compile the shared asset catalog.'
  target_contains CodexStatusWatch 'ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon' || fail 'Watch target must compile AppIcon.'
  target_contains CodexStatus 'target: CodexStatusWidget' || fail 'iPhone app must contain its widget extension.'
  target_contains CodexStatus 'target: CodexStatusWatch' || fail 'iPhone app must embed the Watch app.'
  target_contains CodexStatusWatch 'target: CodexStatusWatchWidget' || fail 'Watch app must contain its widget extension.'
  if target_contains CodexStatusWidget 'ASSETCATALOG_COMPILER_APPICON_NAME'; then
    fail 'The iPhone widget must inherit the containing app icon.'
  fi
  if target_contains CodexStatusWatchWidget 'ASSETCATALOG_COMPILER_APPICON_NAME'; then
    fail 'The Watch widget must inherit the containing Watch app icon.'
  fi

  local width height colorspace channels opaque
  read -r width height colorspace channels opaque < <(
    identify -format '%w %h %[colorspace] %[channels] %[opaque]\n' "${destination_png}"
  )
  [[ "${width}" == "1024" && "${height}" == "1024" && "${colorspace}" == "sRGB" &&
    "${channels}" == "srgb" && "${opaque}" == "true" ]] ||
    fail 'App icon must be an opaque 1024x1024 sRGB PNG.'
}

if [[ "${1:-}" == "--check" ]]; then
  [[ "$#" -eq 1 ]] || fail 'Usage: render_app_icon.sh [--check]'
  validate_contract
  sha256sum "${source_svg}" "${destination_png}"
  exit 0
fi
[[ "$#" -eq 0 ]] || fail 'Usage: render_app_icon.sh [--check]'

chrome_bin="${CHROME_BIN:-}"
if [[ -z "${chrome_bin}" ]]; then
  for candidate in google-chrome-stable google-chrome chromium chromium-browser; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      chrome_bin="$(command -v "${candidate}")"
      break
    fi
  done
fi

[[ -n "${chrome_bin}" && -x "${chrome_bin}" ]] || fail 'A Chrome or Chromium executable is required to render the app icon.'
command -v convert >/dev/null 2>&1 || fail 'ImageMagick convert is required to normalize the app icon PNG.'

if ! "${chrome_bin}" \
  --headless \
  --disable-gpu \
  --no-sandbox \
  --hide-scrollbars \
  --force-device-scale-factor=1 \
  --window-size=1024,1024 \
  --screenshot="${render_tmp}/browser.png" \
  "file://${source_svg}" >"${render_tmp}/chrome.log" 2>&1; then
  printf 'Chrome failed to render the app icon.\n' >&2
  sed -n '1,80p' "${render_tmp}/chrome.log" >&2
  exit 1
fi

convert "${render_tmp}/browser.png" \
  -alpha off \
  -colorspace sRGB \
  -strip \
  "${render_tmp}/CodexStatus-1024.png"

install -m 0644 "${render_tmp}/CodexStatus-1024.png" "${destination_png}"
validate_contract
sha256sum "${source_svg}" "${destination_png}"
