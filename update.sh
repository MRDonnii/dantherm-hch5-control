#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
app=/opt/dantherm-passivelink-webui
admin=/opt/dantherm-webui
state_dir=/var/lib/dantherm-hch5-ha
config=/etc/dantherm-passivelink-webui/controller.yaml
env_file=/etc/dantherm-passivelink-webui/gateway.env
venv=${app}/venv

required_source=(
  gateway/dantherm_controller_gateway.py
  gateway/controller_runtime.py
  gateway/controller_dashboard_server.py
  gateway/dashboard_server.py
  gateway/webui_auth.py
  gateway/webui/index.html
  gateway/webui/controller.html
  gateway/webui/login.html
  systemd/dantherm-webui-gateway.service
  systemd/dantherm-webui-admin.service
  VERSION
)
for rel in "${required_source[@]}"; do
  [[ -f ${source_dir}/${rel} ]] || { echo "Update source is incomplete: ${rel} missing." >&2; exit 2; }
done
[[ -x ${venv}/bin/python ]] || { echo "Existing HCH5 Control virtualenv is missing; use the installer/recovery path." >&2; exit 2; }
[[ -f ${config} && -f ${env_file} ]] || { echo "Persistent HCH5 Control configuration is missing; refusing in-place update." >&2; exit 2; }

read_env() {
  local key=$1
  sed -n "s/^${key}=//p" "${env_file}" | head -1
}
web_port=$(read_env WEBUI_PORT); web_port=${web_port:-8080}
raw_port=$(read_env GATEWAY_PORT); raw_port=${raw_port:-4196}
device=$(read_env RS485_DEVICE)
controller_token=$(read_env DANTHERM_CONTROLLER_TOKEN)
[[ ${web_port} =~ ^[0-9]+$ && ${raw_port} =~ ^[0-9]+$ ]] || { echo "Invalid saved port configuration." >&2; exit 2; }
[[ ${device} == /dev/serial/by-id/* ]] || { echo "Saved RS485 device is not a stable /dev/serial/by-id/... path; refusing restart." >&2; exit 2; }
[[ -e ${device} ]] || { echo "Saved RS485 device is currently unavailable: ${device}. Live service is left untouched." >&2; exit 2; }

for legacy in dantherm-gateway.service dantherm-pi-reboot-api.service; do
  if systemctl is-active --quiet "${legacy}" 2>/dev/null; then
    echo "Legacy service ${legacy} is active; it must be stopped/masked before updating to avoid a port conflict." >&2
    exit 2
  fi
done

[[ -d ${state_dir} ]] || { echo "Persistent state directory ${state_dir} is missing; use the installer/recovery path." >&2; exit 2; }
[[ -r ${state_dir} ]] || { echo "Persistent state directory ${state_dir} is not readable; refusing update." >&2; exit 2; }

stage=$(mktemp -d /tmp/hch5-control-stage.XXXXXX)
cleanup(){ rm -rf -- "${stage}"; }
trap cleanup EXIT
install -d "${stage}/webui"
install -m 0755 "${source_dir}"/gateway/*.py "${stage}/"
install -m 0644 "${source_dir}"/gateway/webui/* "${stage}/webui/"
install -m 0644 "${source_dir}/VERSION" "${stage}/VERSION"

echo "[1/6] Validating staged Python files..."
"${venv}/bin/python" -m py_compile "${stage}"/*.py
PYTHONPATH="${stage}" "${venv}/bin/python" - <<'PY'
import importlib
modules = (
    "webui_auth",
    "dashboard_server",
    "controller_core",
    "controller_runtime",
    "controller_dashboard_server",
    "dantherm_controller_gateway",
)
for module in modules:
    importlib.import_module(module)
print("runtime imports: OK")
PY

echo "[2/6] Validating persistent configuration..."
"${venv}/bin/python" - "${config}" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as handle:
    payload = yaml.safe_load(handle)
if not isinstance(payload, dict):
    raise SystemExit("controller.yaml is not a YAML object")
for section in ("serial", "raw_tcp", "dashboard", "controller"):
    if not isinstance(payload.get(section), dict):
        raise SystemExit(f"controller.yaml missing required section: {section}")
print("controller.yaml: OK")
PY

auth_file=${state_dir}/webui-auth.json
auth_before=""
if [[ -f ${auth_file} ]]; then
  auth_before=$(sha256sum "${auth_file}" | awk '{print $1}')
  "${venv}/bin/python" - "${auth_file}" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
if not isinstance(data, dict) or not data.get("username") or not data.get("salt") or not data.get("password_hash"):
    raise SystemExit("webui-auth.json is incomplete")
print("WebUI owner store: OK")
PY
fi
config_before=$(sha256sum "${config}" | awk '{print $1}')
env_before=$(sha256sum "${env_file}" | awk '{print $1}')

required_assets=(index.html controller.html login.html dashboard.js controller.js smartcontrol.js theme.css dashboard.css)
for asset in "${required_assets[@]}"; do
  [[ -s ${stage}/webui/${asset} ]] || { echo "Staged WebUI asset missing/empty: ${asset}" >&2; exit 2; }
done
if command -v node >/dev/null 2>&1; then
  echo "[3/6] Validating staged JavaScript..."
  for js in "${stage}"/webui/*.js; do node --check "${js}"; done
else
  echo "[3/6] node not installed on Pi; JavaScript syntax is covered by GitHub Validate."
fi

backup="/var/backups/hch5-control-update-$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 "${backup}"
tar -czf "${backup}/app-code.tar.gz" --exclude='venv' -C "${app}" .
[[ -f ${admin}/dantherm_pi_admin_api.py ]] && cp -a "${admin}/dantherm_pi_admin_api.py" "${backup}/"
[[ -f ${admin}/diagnostics_report.py ]] && cp -a "${admin}/diagnostics_report.py" "${backup}/"
[[ -f /etc/systemd/system/dantherm-webui-gateway.service ]] && cp -a /etc/systemd/system/dantherm-webui-gateway.service "${backup}/"
[[ -f /etc/systemd/system/dantherm-webui-admin.service ]] && cp -a /etc/systemd/system/dantherm-webui-admin.service "${backup}/"

rollback_ready=1
rollback() {
  local rc=${1:-1}
  echo "HCH5 Control update failed validation (rc=${rc}); restoring previous build." >&2
  set +e
  if [[ -f ${backup}/app-code.tar.gz ]]; then
    find "${app}" -mindepth 1 -maxdepth 1 ! -name venv -exec rm -rf -- {} +
    tar -xzf "${backup}/app-code.tar.gz" -C "${app}"
    chown -R passivelink-webui:passivelink-webui "${app}"
  fi
  [[ -f ${backup}/dantherm_pi_admin_api.py ]] && install -o root -g root -m 0755 "${backup}/dantherm_pi_admin_api.py" "${admin}/dantherm_pi_admin_api.py"
  [[ -f ${backup}/diagnostics_report.py ]] && install -o root -g root -m 0644 "${backup}/diagnostics_report.py" "${admin}/diagnostics_report.py"
  [[ -f ${backup}/dantherm-webui-gateway.service ]] && install -o root -g root -m 0644 "${backup}/dantherm-webui-gateway.service" /etc/systemd/system/
  [[ -f ${backup}/dantherm-webui-admin.service ]] && install -o root -g root -m 0644 "${backup}/dantherm-webui-admin.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl restart dantherm-webui-gateway.service
  sleep 2
  if systemctl is-active --quiet dantherm-webui-gateway.service \
      && curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:${web_port}/api/auth/status"; then
    echo "Rollback health check: OK. Previous controller is online again." >&2
  else
    echo "CRITICAL: rollback completed on disk but gateway health check failed." >&2
    systemctl status dantherm-webui-gateway.service --no-pager -l >&2 || true
    journalctl -u dantherm-webui-gateway.service -n 80 --no-pager >&2 || true
  fi
  echo "Rollback backup kept at ${backup}." >&2
}
on_error(){
  local rc=$?
  trap - ERR
  if [[ ${rollback_ready:-0} -eq 1 ]]; then rollback "${rc}"; fi
  exit "${rc}"
}
trap on_error ERR

echo "[4/6] Installing validated files while current process remains running..."
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

echo "[5/6] Validating installed files before restart..."
"${venv}/bin/python" -m py_compile "${app}"/*.py
PYTHONPATH="${app}" "${venv}/bin/python" - <<'PY'
import importlib
for module in ("webui_auth", "dashboard_server", "controller_core", "controller_runtime", "controller_dashboard_server", "dantherm_controller_gateway"):
    importlib.import_module(module)
print("installed runtime imports: OK")
PY
[[ $(sha256sum "${config}" | awk '{print $1}') == "${config_before}" ]] || { echo "Persistent controller config changed during update." >&2; false; }
[[ $(sha256sum "${env_file}" | awk '{print $1}') == "${env_before}" ]] || { echo "Persistent environment changed during update." >&2; false; }
if [[ -n ${auth_before} ]]; then
  [[ -f ${auth_file} ]] || { echo "WebUI owner store disappeared during update." >&2; false; }
  [[ $(sha256sum "${auth_file}" | awk '{print $1}') == "${auth_before}" ]] || { echo "WebUI owner store changed during update." >&2; false; }
fi

echo "[6/6] Restarting once and performing live health validation..."
systemctl daemon-reload
systemctl restart dantherm-webui-gateway.service

healthy_hits=0
stable_pid=""
for _ in $(seq 1 20); do
  sleep 1
  pid=$(systemctl show dantherm-webui-gateway.service -p MainPID --value 2>/dev/null || true)
  if systemctl is-active --quiet dantherm-webui-gateway.service \
      && [[ ${pid} =~ ^[1-9][0-9]*$ ]] \
      && curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:${web_port}/api/auth/status"; then
    if [[ -z ${stable_pid} || ${stable_pid} == "${pid}" ]]; then
      stable_pid=${pid}; healthy_hits=$((healthy_hits + 1))
    else
      stable_pid=${pid}; healthy_hits=1
    fi
    [[ ${healthy_hits} -ge 5 ]] && break
  else
    healthy_hits=0; stable_pid=""
  fi
done
[[ ${healthy_hits} -ge 5 ]] || { echo "Gateway did not stay healthy with one stable PID for five consecutive checks." >&2; false; }

expected_configured=0; [[ -n ${auth_before} ]] && expected_configured=1
curl -fsS --max-time 3 "http://127.0.0.1:${web_port}/api/auth/status" \
  | python3 -c 'import json,sys; expected=int(sys.argv[1]); data=json.load(sys.stdin); assert isinstance(data.get("configured"), bool); assert (not expected) or data["configured"] is True' "${expected_configured}"

if [[ -n ${controller_token} ]]; then
  curl -fsS --max-time 3 -H "Authorization: Bearer ${controller_token}" \
    "http://127.0.0.1:${web_port}/api/controller/state" \
    | python3 -c 'import json,sys; data=json.load(sys.stdin); assert isinstance(data,dict); assert "active_master" in data'
else
  echo "Controller token is missing; refusing to accept an incompletely configured update." >&2
  false
fi

python3 - "${raw_port}" <<'PY'
import socket, sys
port = int(sys.argv[1])
with socket.create_connection(("127.0.0.1", port), timeout=2):
    pass
print("raw TCP listener: OK")
PY

[[ $(sha256sum "${config}" | awk '{print $1}') == "${config_before}" ]]
[[ $(sha256sum "${env_file}" | awk '{print $1}') == "${env_before}" ]]
if [[ -n ${auth_before} ]]; then
  [[ $(sha256sum "${auth_file}" | awk '{print $1}') == "${auth_before}" ]]
fi

rollback_ready=0
trap - ERR
echo "HCH5 Control updated to $(cat "${source_dir}/VERSION")."
echo "Preflight: OK · imports/config/assets/auth/device"
echo "Live health: OK · stable process/WebUI/auth/controller API/raw TCP"
echo "Persistent config and owner login: preserved"
echo "Backup: ${backup}"
