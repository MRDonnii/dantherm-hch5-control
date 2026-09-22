#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f ${source_dir}/gateway/dantherm_controller_gateway.py ]] || { echo "Invalid HCH5 Control source tree." >&2; exit 2; }
[[ -f ${source_dir}/VERSION ]] || { echo "VERSION missing." >&2; exit 2; }

app=/opt/dantherm-passivelink-webui
admin=/opt/dantherm-webui
backup="/var/backups/hch5-control-update-$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 "${backup}"

# Back up only replaceable application code. Persistent state/config is never removed.
[[ -d ${app} ]] && tar -czf "${backup}/app-code.tar.gz" \
  --exclude='venv' -C "${app}" . 2>/dev/null || true
[[ -f ${admin}/dantherm_pi_admin_api.py ]] && cp -a "${admin}/dantherm_pi_admin_api.py" "${backup}/"

install -d -o passivelink-webui -g passivelink-webui "${app}" "${app}/webui"
install -o passivelink-webui -g passivelink-webui -m 0755 "${source_dir}"/gateway/*.py "${app}/"
install -o passivelink-webui -g passivelink-webui -m 0644 "${source_dir}"/gateway/webui/* "${app}/webui/"
install -o passivelink-webui -g passivelink-webui -m 0644 "${source_dir}/VERSION" "${app}/VERSION"

install -d -m 0755 "${admin}"
install -o root -g root -m 0755 "${source_dir}/gateway/dantherm_pi_admin_api.py" "${admin}/dantherm_pi_admin_api.py"
install -o root -g root -m 0644 "${source_dir}/gateway/diagnostics_report.py" "${admin}/diagnostics_report.py"
install -o root -g root -m 0644 "${source_dir}/systemd/dantherm-webui-gateway.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/systemd/dantherm-webui-admin.service" /etc/systemd/system/
if [[ -f ${source_dir}/systemd/dantherm-webui-onewire.service && -f /etc/systemd/system/dantherm-webui-onewire.service ]]; then
  install -o root -g root -m 0644 "${source_dir}/systemd/dantherm-webui-onewire.service" /etc/systemd/system/
fi

systemctl daemon-reload
systemctl restart dantherm-webui-gateway.service
# Restart helper last; this updater may itself have been started by that service.
systemctl restart dantherm-webui-admin.service || true

echo "HCH5 Control updated to $(cat "${source_dir}/VERSION")."
echo "Backup: ${backup}"
