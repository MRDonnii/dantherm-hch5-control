#!/usr/bin/env bash
set -euo pipefail
[[ ${EUID} -eq 0 ]] || { echo "Run as root with sudo." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
command -v tar >/dev/null || { echo "tar is required." >&2; exit 1; }

version=$(curl -fsSL "https://raw.githubusercontent.com/MRDonnii/dantherm-hch-passivelink-webui/beta-latest/VERSION")
ref="v${version}"
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
curl -fsSL "https://codeload.github.com/MRDonnii/dantherm-hch-passivelink-webui/tar.gz/${ref}" \
  | tar -xz -C "$tmp" --strip-components=1

build=$(cat "$tmp/VERSION")

if [[ -x /opt/dantherm-passivelink-webui/venv/bin/python \
      && -f /opt/dantherm-passivelink-webui/dantherm_controller_gateway.py \
      && -f /etc/dantherm-passivelink-webui/gateway.env \
      && -f /etc/dantherm-passivelink-webui/controller.yaml ]]; then
  echo "Existing HCH5 Control installation detected; using transactional update/recovery."
  HCH5_UPDATE_BUILD="${build:-unknown}" bash "$tmp/update.sh"
  install -o root -g root -m 0755 "$tmp/update.sh" /opt/dantherm-webui/update.sh
  systemctl restart dantherm-webui-admin.service
  systemctl is-active --quiet dantherm-webui-admin.service || {
    echo "The updated admin service did not become active." >&2
    exit 1
  }
  echo "HCH5 Control $(cat "$tmp/VERSION") installed safely."
  exit 0
fi

has_device=0
for arg in "$@"; do [[ ${arg} == "--device" ]] && has_device=1; done
if [[ ${has_device} -eq 0 ]]; then
  saved=""
  if [[ -f /etc/dantherm-passivelink-webui/gateway.env ]]; then
    saved=$(sed -n 's/^RS485_DEVICE=//p' /etc/dantherm-passivelink-webui/gateway.env | head -1)
  fi
  if [[ ${saved} == /dev/serial/by-id/* && -e ${saved} ]]; then
    set -- --device "${saved}" "$@"
  else
    mapfile -t adapters < <(find /dev/serial/by-id -mindepth 1 -maxdepth 1 -type l -print 2>/dev/null | sort || true)
    if [[ ${#adapters[@]} -eq 1 ]]; then
      echo "Using the only stable serial adapter found: ${adapters[0]}"
      set -- --device "${adapters[0]}" "$@"
    elif [[ ${#adapters[@]} -eq 0 ]]; then
      echo "No stable /dev/serial/by-id/... adapter found. Connect the RS485 adapter or pass --device explicitly." >&2
      exit 2
    else
      echo "Multiple serial adapters found; refusing to guess. Re-run with --device /dev/serial/by-id/..." >&2
      printf '  %s\n' "${adapters[@]}" >&2
      exit 2
    fi
  fi
fi

bash "$tmp/install.sh" "$@"
install -o passivelink-webui -g passivelink-webui -m 0644 "$tmp/VERSION" /opt/dantherm-passivelink-webui/VERSION
printf '%s\n' "${build:-unknown}" > /opt/dantherm-passivelink-webui/BUILD
chown passivelink-webui:passivelink-webui /opt/dantherm-passivelink-webui/BUILD
chmod 0644 /opt/dantherm-passivelink-webui/BUILD
install -o root -g root -m 0755 "$tmp/update.sh" /opt/dantherm-webui/update.sh

echo "HCH5 Control $(cat "$tmp/VERSION") installed."
