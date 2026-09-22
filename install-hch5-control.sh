#!/usr/bin/env bash
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo "Run as root with sudo." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
command -v tar >/dev/null || { echo "tar is required." >&2; exit 1; }

ref="beta/1.1-modern-controller"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
curl -fsSL "https://api.github.com/repos/MRDonnii/dantherm-hch-passivelink-webui/tarball/${ref}" \
  | tar -xz -C "$tmp" --strip-components=1

bash "$tmp/install.sh" "$@"
install -o passivelink-webui -g passivelink-webui -m 0644 "$tmp/VERSION" /opt/dantherm-passivelink-webui/VERSION
build=$(curl -fsSL "https://api.github.com/repos/MRDonnii/dantherm-hch-passivelink-webui/branches/beta%2F1.1-modern-controller" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"]["sha"])' 2>/dev/null || true)
printf '%s\n' "${build:-unknown}" > /opt/dantherm-passivelink-webui/BUILD
chown passivelink-webui:passivelink-webui /opt/dantherm-passivelink-webui/BUILD
chmod 0644 /opt/dantherm-passivelink-webui/BUILD
# Install the safe in-place updater source for diagnostics/reference.
install -o root -g root -m 0755 "$tmp/update.sh" /opt/dantherm-webui/update.sh

echo "HCH5 Control $(cat "$tmp/VERSION") installed."
