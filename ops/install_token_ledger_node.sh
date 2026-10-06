#!/usr/bin/env bash
# Install or update the fleet token-ledger exporter on one worker node.
#
#   ops/install_token_ledger_node.sh <node-name> <node-ssh-target> [master-ssh-target]
#
# Run from any operator machine that can ssh (as root) to both the worker and
# master. The worker gets the stdlib-only package, its own ed25519 key, the
# pinned master host key, its node config (existing keys such as explicit
# ``cells`` are kept), and the systemd timer. Master gets one
# authorized_keys line that is `restrict`ed to a forced ingest command for
# exactly this node, so the key can do nothing else.
set -Eeuo pipefail

node="${1:?node name (e.g. jeff-dev)}"
target="${2:?ssh target for the node (e.g. root@94.130.17.246)}"
master="${3:-root@135.181.182.48}"
master_host="${master#*@}"
readonly LIB=/usr/local/lib/pitchai-token-ledger
readonly KEY=/root/.ssh/token_ledger_ed25519
readonly KNOWN_HOSTS=/var/lib/pitchai-token-ledger/known_hosts
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly REPO_ROOT

[[ "${node}" =~ ^[a-z0-9][a-z0-9-]{0,40}$ ]] || { printf 'Invalid node name: %s\n' "${node}" >&2; exit 1; }
version="$(git -C "${REPO_ROOT}" rev-parse --verify HEAD)"

printf 'Installing package %s on %s (%s)\n' "${version:0:12}" "${node}" "${target}"
COPYFILE_DISABLE=1 tar -C "${REPO_ROOT}/auth_usage_dashboard" --exclude __pycache__ -cf - token_ledger \
  | ssh "${target}" "set -e; install -d -m 755 ${LIB}; rm -rf ${LIB}/token_ledger.new; mkdir ${LIB}/token_ledger.new; tar -C ${LIB}/token_ledger.new --strip-components=1 -xf - 2>/dev/null; printf '%s\n' '${version}' > ${LIB}/token_ledger.new/VERSION; rm -rf ${LIB}/token_ledger.old; [ -d ${LIB}/token_ledger ] && mv ${LIB}/token_ledger ${LIB}/token_ledger.old; mv ${LIB}/token_ledger.new ${LIB}/token_ledger; rm -rf ${LIB}/token_ledger.old"

master_key="$(ssh "${master}" 'cat /etc/ssh/ssh_host_ed25519_key.pub' | awk '{print $1" "$2}')"
[[ "${master_key}" == ssh-ed25519\ * ]] || { printf 'Could not read the master host key.\n' >&2; exit 1; }

public_key="$(ssh "${target}" "set -e
install -d -m 700 /var/lib/pitchai-token-ledger /etc/pitchai-token-ledger
[ -f ${KEY} ] || ssh-keygen -q -t ed25519 -N '' -C 'token-ledger-${node}' -f ${KEY}
printf '%s %s\n' '${master_host}' '${master_key}' > ${KNOWN_HOSTS}
chmod 600 ${KNOWN_HOSTS}
cat ${KEY}.pub")"
[[ "${public_key}" == ssh-ed25519\ * ]] || { printf 'Could not read the node public key.\n' >&2; exit 1; }

# Set node, delivery and master, but keep every other key of an existing config
# (explicit cells, extra homes, budgets), so the node never depends on its hostname.
ssh "${target}" python3 - /etc/pitchai-token-ledger/config.json "${node}" "${master}" <<'PY'
import json
import sys
from pathlib import Path

path, node, master = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
try:
    loaded = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    loaded = {}
config = loaded if isinstance(loaded, dict) else {}
config.update({"node": node, "delivery": "ssh", "master": master})
staged = path.with_name(path.name + ".new")
staged.write_text(json.dumps(config) + "\n", encoding="utf-8")
staged.chmod(0o644)
staged.replace(path)
PY
key_body="$(awk '{print $2}' <<<"${public_key}")"

forced="restrict,command=\"PYTHONPATH=${LIB} PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m token_ledger ingest --node ${node}\" ssh-ed25519 ${key_body} token-ledger-${node}"
ssh "${master}" "set -e
touch /root/.ssh/authorized_keys
if grep -qF '${key_body}' /root/.ssh/authorized_keys; then
  grep -vF '${key_body}' /root/.ssh/authorized_keys > /root/.ssh/authorized_keys.token-ledger.tmp
  cat /root/.ssh/authorized_keys.token-ledger.tmp > /root/.ssh/authorized_keys
  rm -f /root/.ssh/authorized_keys.token-ledger.tmp
fi
printf '%s\n' '${forced}' >> /root/.ssh/authorized_keys"

COPYFILE_DISABLE=1 tar -C "${REPO_ROOT}/ops" -cf - token-ledger-export.service token-ledger-export.timer \
  | ssh "${target}" "set -e; tar -C /etc/systemd/system -xf - 2>/dev/null; chmod 644 /etc/systemd/system/token-ledger-export.service /etc/systemd/system/token-ledger-export.timer; systemctl daemon-reload; systemctl enable --now token-ledger-export.timer >/dev/null; systemctl start token-ledger-export.service; PYTHONPATH=${LIB} python3 -m token_ledger status"
printf 'Installed token ledger exporter on %s\n' "${node}"
