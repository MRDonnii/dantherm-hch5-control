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

# Back up replaceable application code and service units. Persistent state/config
# under /var/lib and /etc is never removed or overwritten by rollback.
[[ -d ${app} ]] && tar -czf "${backup}/app-code.tar.gz" \
  --exclude='venv' -C "${app}" . 2>/dev/null || true
[[ -f ${admin}/dantherm_pi_admin_api.py ]] && cp -a "${admin}/dantherm_pi_admin_api.py" "${backup}/"
[[ -f /etc/systemd/system/dantherm-webui-gateway.service ]] && cp -a /etc/systemd/system/dantherm-webui-gateway.service "${backup}/"
[[ -f /etc/systemd/system/dantherm-webui-admin.service ]] && cp -a /etc/systemd/system/dantherm-webui-admin.service "${backup}/"

rollback_ready=1
rollback() {
  local rc=${1:-1}
  echo "HCH5 Control update failed health validation (rc=${rc}); rolling back application code." >&2
  set +e

  if [[ -f ${backup}/app-code.tar.gz ]]; then
    # Keep the existing virtualenv, but remove all newly installed application
    # files before restoring the exact previous code snapshot.
    find "${app}" -mindepth 1 -maxdepth 1 ! -name venv -exec rm -rf -- {} +
    tar -xzf "${backup}/app-code.tar.gz" -C "${app}"
    chown -R passivelink-webui:passivelink-webui "${app}"
  fi
  [[ -f ${backup}/dantherm_pi_admin_api.py ]] && install -o root -g root -m 0755 "${backup}/dantherm_pi_admin_api.py" "${admin}/dantherm_pi_admin_api.py"
  [[ -f ${backup}/dantherm-webui-gateway.service ]] && install -o root -g root -m 0644 "${backup}/dantherm-webui-gateway.service" /etc/systemd/system/
  [[ -f ${backup}/dantherm-webui-admin.service ]] && install -o root -g root -m 0644 "${backup}/dantherm-webui-admin.service" /etc/systemd/system/

  systemctl daemon-reload
  systemctl restart dantherm-webui-gateway.service
  echo "Rollback completed. Backup kept at ${backup}." >&2
}

trap 'rc=$?; trap - ERR; if [[ ${rollback_ready} -eq 1 ]]; then rollback "${rc}"; fi; exit "${rc}"' ERR

install -d -o passivelink-webui -g passivelink-webui "${app}" "${app}/webui"
install -o passivelink-webui -g passivelink-webui -m 0755 "${source_dir}"/gateway/*.py "${app}/"
install -o passivelink-webui -g passivelink-webui -m 0644 "${source_dir}"/gateway/webui/* "${app}/webui/"
install -o passivelink-webui -g passivelink-webui -m 0644 "${source_dir}/VERSION" "${app}/VERSION"
printf '%s\n' "${HCH5_UPDATE_BUILD:-unknown}" > "${app}/BUILD"
chown passivelink-webui:passivelink-webui "${app}/BUILD"
chmod 0644 "${app}/BUILD"

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

# Require the gateway to stay active and the local HTTP listener to answer for
# three consecutive checks. A crash-loop or a failed WebUI bind therefore rolls
# back automatically instead of leaving the ventilation controller offline.
healthy_hits=0
for _ in $(seq 1 12); do
  sleep 1
  if systemctl is-active --quiet dantherm-webui-gateway.service \
      && curl -sS -o /dev/null --max-time 2 http://127.0.0.1:8080/; then
    healthy_hits=$((healthy_hits + 1))
    if [[ ${healthy_hits} -ge 3 ]]; then
      break
    fi
  else
    healthy_hits=0
  fi
done

if [[ ${healthy_hits} -lt 3 ]]; then
  echo "Gateway/WebUI did not become stably healthy after update." >&2
  false
fi

rollback_ready=0
trap - ERR
# The admin helper schedules its own restart after this updater has exited.

echo "HCH5 Control updated to $(cat "${source_dir}/VERSION")."
echo "Health check: OK (gateway + local WebUI)."
echo "Backup: ${backup}"
