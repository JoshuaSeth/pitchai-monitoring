#!/usr/bin/env bash
set -Eeuo pipefail

expected=(
  send-message
  --requester seth-ori
  --message-class automation
  --sensitive
  --message "safe message"
)
actual=("$@")

if [[ "$#" -ne "${#expected[@]}" ]]; then
  exit 97
fi
for index in "${!expected[@]}"; do
  if [[ "${actual[index]}" != "${expected[index]}" ]]; then
    exit 98
  fi
done

printf '{"destination_ref":"seth-ori","policy":"personal-first","requester_key":"seth-ori","route_kind":"private","status":"sent"}\n'
