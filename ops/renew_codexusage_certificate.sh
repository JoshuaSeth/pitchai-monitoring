#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_HOST="pitchai-dev"
readonly CERT_NAME="codexusage.pitchai.net"
readonly CERTBOT_IMAGE="certbot/certbot@sha256:6bb19cff0b3972a69855686e0ccbd20b98dbfae2aa43845a5df48947ba1401b4"
readonly CERT_FILE="/etc/letsencrypt/live/${CERT_NAME}/cert.pem"

if [[ "$(hostname -s)" != "${EXPECTED_HOST}" ]]; then
  printf 'Refusing renewal: expected host %s, found %s\n' "${EXPECTED_HOST}" "$(hostname -s)" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  printf 'Run certificate renewal as root.\n' >&2
  exit 1
fi

for path in /etc/letsencrypt /var/lib/letsencrypt /var/log/letsencrypt /var/www/letsencrypt "${CERT_FILE}"; do
  if [[ ! -e "${path}" ]]; then
    printf 'Required renewal path is missing: %s\n' "${path}" >&2
    exit 1
  fi
done

before_fingerprint="$(openssl x509 -in "${CERT_FILE}" -noout -fingerprint -sha256)"

if ! docker image inspect "${CERTBOT_IMAGE}" >/dev/null 2>&1; then
  docker pull "${CERTBOT_IMAGE}" >/dev/null
fi

docker run --rm \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/log/letsencrypt:/var/log/letsencrypt \
  -v /var/www/letsencrypt:/var/www/letsencrypt \
  "${CERTBOT_IMAGE}" \
  renew --cert-name "${CERT_NAME}" --quiet --no-random-sleep-on-renew

after_fingerprint="$(openssl x509 -in "${CERT_FILE}" -noout -fingerprint -sha256)"
if [[ "${before_fingerprint}" != "${after_fingerprint}" ]]; then
  nginx -t
  systemctl reload nginx
  printf 'Renewed %s and reloaded Nginx.\n' "${CERT_NAME}"
else
  printf '%s is not due for renewal.\n' "${CERT_NAME}"
fi
