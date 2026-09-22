#!/usr/bin/env bash
set -euo pipefail

usage(){ cat <<'EOF'
Usage: sudo ./install.sh --device /dev/serial/by-id/YOUR_ADAPTER [options]
  --gateway-port PORT   Raw TCP port for Home Assistant (default: 4196)
  --web-port PORT       WebUI/controller API port (default: 8080)
  --enable-onewire      Install optional DS18B20/Pi diagnostics service
  --beta                Install the exact v1.1.0-beta.1 prerelease
  --ref REF             Install an exact GitHub tag/branch when piping this script
EOF
}

device=""; gateway_port=4196; web_port=8080; onewire=0; source_ref=""; beta=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) device=${2:-}; shift 2;;
    --gateway-port) gateway_port=${2:-}; shift 2;;
    --web-port) web_port=${2:-}; shift 2;;
    --enable-onewire) onewire=1; shift;;
    --beta) beta=1; shift;;
    --ref) source_ref=${2:-}; shift 2;;
    -h|--help) usage; exit 0;;
    *) usage >&2; exit 2;;
  esac
done

if [[ ${beta} -eq 1 ]]; then
  [[ -z ${source_ref} ]] || { echo "Use either --beta or --ref, not both." >&2; exit 2; }
  source_ref="v1.1.0-beta.1"
fi

[[ ${EUID} -eq 0 ]] || { echo "Run as root with sudo." >&2; exit 1; }
[[ ${device} == /dev/serial/by-id/* ]] || { echo "Use a stable /dev/serial/by-id/... path." >&2; exit 2; }
[[ ${gateway_port} =~ ^[0-9]+$ && ${web_port} =~ ^[0-9]+$ ]] || { echo "Ports must be numeric." >&2; exit 2; }
command -v apt-get >/dev/null || { echo "This installer supports Raspberry Pi OS, Debian and Ubuntu (apt)." >&2; exit 1; }

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || pwd)
temp_dir=""
if [[ ! -f ${source_dir}/gateway/dantherm_controller_gateway.py ]]; then
  temp_dir=$(mktemp -d)
  trap '[[ -n ${temp_dir} ]] && rm -rf -- "${temp_dir}"' EXIT
  if [[ -n ${source_ref} ]]; then
    tarball_url="https://api.github.com/repos/MRDonnii/dantherm-hch-passivelink-webui/tarball/${source_ref}"
  else
    tarball_url=$(curl -fsSL https://api.github.com/repos/MRDonnii/dantherm-hch-passivelink-webui/releases/latest \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["tarball_url"])')
  fi
  curl -fsSL "${tarball_url}" | tar -xz -C "${temp_dir}" --strip-components=1
  source_dir=${temp_dir}
fi

[[ -f ${source_dir}/gateway/dantherm_controller_gateway.py ]] || {
  echo "Selected source does not contain the controller gateway." >&2
  exit 1
}

apt-get update
apt-get install -y python3 python3-venv python3-pip curl openssl

if ! id passivelink-webui >/dev/null 2>&1; then
  useradd --system --home /opt/dantherm-passivelink-webui --shell /usr/sbin/nologin --groups dialout,video passivelink-webui
else
  usermod -aG dialout,video passivelink-webui
fi

install -d -o passivelink-webui -g passivelink-webui /opt/dantherm-passivelink-webui
install -d -o root -g passivelink-webui -m 0750 /etc/dantherm-passivelink-webui
install -d -o passivelink-webui -g passivelink-webui -m 0750 /var/lib/dantherm-hch5-ha
chown -R passivelink-webui:passivelink-webui /var/lib/dantherm-hch5-ha

backup="/var/backups/dantherm-webui-$(date +%Y%m%d-%H%M%S)"
install -d -m 0700 "${backup}"
for path in \
  /etc/dantherm-passivelink-webui/gateway.env \
  /etc/dantherm-passivelink-webui/controller.yaml \
  /etc/dantherm-passivelink-webui/onewire.json \
  /var/lib/dantherm-hch5-ha/controller.json \
  /var/lib/dantherm-hch5-ha/webui-auth.json; do
  [[ -e ${path} ]] && cp -a "${path}" "${backup}/"
done

install -o passivelink-webui -g passivelink-webui -m 0755 "${source_dir}"/gateway/*.py /opt/dantherm-passivelink-webui/
install -d -o passivelink-webui -g passivelink-webui /opt/dantherm-passivelink-webui/webui
install -o passivelink-webui -g passivelink-webui -m 0644 "${source_dir}"/gateway/webui/* /opt/dantherm-passivelink-webui/webui/

if [[ ! -x /opt/dantherm-passivelink-webui/venv/bin/python ]]; then
  runuser -u passivelink-webui -- python3 -m venv /opt/dantherm-passivelink-webui/venv
fi
runuser -u passivelink-webui -- /opt/dantherm-passivelink-webui/venv/bin/pip install --upgrade pip
runuser -u passivelink-webui -- /opt/dantherm-passivelink-webui/venv/bin/pip install \
  pyserial==3.5 paho-mqtt PyYAML

random_token(){ openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))'; }
existing_env=/etc/dantherm-passivelink-webui/gateway.env
reboot_token=$(random_token)
controller_token=$(random_token)
if [[ -f ${existing_env} ]]; then
  previous=$(sed -n 's/^DANTHERM_REBOOT_TOKEN=//p' "${existing_env}" | head -1)
  [[ -n ${previous} ]] && reboot_token=${previous}
  previous=$(sed -n 's/^DANTHERM_CONTROLLER_TOKEN=//p' "${existing_env}" | head -1)
  [[ -n ${previous} ]] && controller_token=${previous}
fi

cat > /etc/dantherm-passivelink-webui/gateway.env <<EOF
RS485_DEVICE=${device}
GATEWAY_BIND=0.0.0.0
GATEWAY_PORT=${gateway_port}
WEBUI_BIND=0.0.0.0
WEBUI_PORT=${web_port}
DANTHERM_REBOOT_TOKEN=${reboot_token}
DANTHERM_CONTROLLER_TOKEN=${controller_token}
DANTHERM_ADMIN_URL=http://127.0.0.1:4198
EOF
[[ ${onewire} -eq 1 ]] && echo 'ONEWIRE_URL=http://127.0.0.1:4197/temperatures' >> /etc/dantherm-passivelink-webui/gateway.env
chown root:passivelink-webui /etc/dantherm-passivelink-webui/gateway.env
chmod 0640 /etc/dantherm-passivelink-webui/gateway.env

controller_config=/etc/dantherm-passivelink-webui/controller.yaml
if [[ ! -f ${controller_config} ]]; then
cat > "${controller_config}" <<EOF
device:
  id: dantherm_hch5
  name: Dantherm HCH5
mqtt:
  enabled: false
  topic_prefix: dantherm
  discovery_prefix: homeassistant
  retain: true
serial:
  port: ${device}
  baudrate: 19200
  parity: E
  active_reads_enabled: true
  master_mode: true
raw_tcp:
  enabled: true
  bind: 0.0.0.0
  port: ${gateway_port}
  max_clients: 4
dashboard:
  enabled: true
  bind: 0.0.0.0
  port: ${web_port}
  preheater_url: http://127.0.0.1:4197/temperatures
controller:
  state_file: /var/lib/dantherm-hch5-ha/controller.json
  tick_seconds: 2.0
  master_arbitration:
    detection_window_seconds: 2
    detection_min_foreign_writes: 2
    release_timeout_seconds: 10
    startup_observation_seconds: 10
    own_echo_ttl_seconds: 0.2
control:
  enabled: false
  fireplace_enabled: false
diagnostic_capture:
  directory: /var/lib/dantherm-hch5-ha/direction-captures
filter:
  enabled: false
EOF
else
  # Preserve user configuration and only migrate fields required by the
  # controller-aware entrypoint and fail-safe arbitration.
  /opt/dantherm-passivelink-webui/venv/bin/python - "${controller_config}" "${device}" "${gateway_port}" "${web_port}" <<'PY'
import os
import sys
import tempfile

import yaml

path, device, gateway_port, web_port = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    config = yaml.safe_load(handle) or {}
if not isinstance(config, dict):
    raise SystemExit("Existing controller.yaml must contain a YAML object")

serial = config.setdefault("serial", {})
serial.update(port=device, baudrate=19200, parity="E", active_reads_enabled=True, master_mode=True)
raw_tcp = config.setdefault("raw_tcp", {})
raw_tcp.update(enabled=True, port=int(gateway_port))
raw_tcp.setdefault("bind", "0.0.0.0")
raw_tcp.setdefault("max_clients", 4)
dashboard = config.setdefault("dashboard", {})
dashboard.update(enabled=True, port=int(web_port))
dashboard.setdefault("bind", "0.0.0.0")
controller = config.setdefault("controller", {})
controller.setdefault("state_file", "/var/lib/dantherm-hch5-ha/controller.json")
controller.setdefault("tick_seconds", 2.0)
master = controller.setdefault("master_arbitration", {})
master.setdefault("detection_window_seconds", 2)
master.setdefault("detection_min_foreign_writes", 2)
master.setdefault("release_timeout_seconds", 10)
master.setdefault("startup_observation_seconds", 10)
master["own_echo_ttl_seconds"] = 0.2
# The legacy gateway loop must remain disabled; ControllerRuntime is the only
# Pi controller and cannot be disabled by users.
control = config.setdefault("control", {})
control["enabled"] = False
control["fireplace_enabled"] = False

directory = os.path.dirname(path)
fd, temporary = tempfile.mkstemp(prefix=".controller-", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o640)
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
fi
chown root:passivelink-webui "${controller_config}"
chmod 0640 "${controller_config}"

if [[ ! -f /etc/dantherm-passivelink-webui/onewire.json ]]; then
  install -o root -g passivelink-webui -m 0640 "${source_dir}/gateway/onewire.example.json" /etc/dantherm-passivelink-webui/onewire.json
fi

install -o root -g root -m 0644 "${source_dir}/systemd/dantherm-webui-gateway.service" /etc/systemd/system/
install -o root -g root -m 0644 "${source_dir}/systemd/dantherm-webui-admin.service" /etc/systemd/system/
install -d /opt/dantherm-webui
install -o root -g root -m 0755 "${source_dir}/gateway/dantherm_pi_admin_api.py" /opt/dantherm-webui/dantherm_pi_admin_api.py
install -o root -g root -m 0644 "${source_dir}/gateway/diagnostics_report.py" /opt/dantherm-webui/diagnostics_report.py
install -d -m 0750 /etc/dantherm-webui
cat > /etc/dantherm-webui/admin.env <<EOF
DANTHERM_REBOOT_TOKEN=${reboot_token}
DANTHERM_ADMIN_BIND=127.0.0.1
DANTHERM_ADMIN_PORT=4198
DANTHERM_GATEWAY_SERVICE=dantherm-webui-gateway.service
DANTHERM_ONEWIRE_SERVICE=dantherm-webui-onewire.service
EOF
chmod 0600 /etc/dantherm-webui/admin.env

if [[ ${onewire} -eq 1 ]]; then
  install -m 0644 "${source_dir}/systemd/dantherm-webui-onewire.service" /etc/systemd/system/
fi

systemctl daemon-reload
systemctl enable --now dantherm-webui-admin.service dantherm-webui-gateway.service
[[ ${onewire} -eq 1 ]] && systemctl enable --now dantherm-webui-onewire.service
systemctl restart dantherm-webui-admin.service dantherm-webui-gateway.service

ip=$(hostname -I | awk '{print $1}')
echo "Installed controller gateway. Open http://${ip}:${web_port}/ and create the first owner."
echo "Home Assistant PassiveLink raw TCP: host ${ip}, port ${gateway_port}."
echo "Home Assistant controller API: http://${ip}:${web_port}"
echo "Controller token is stored in /etc/dantherm-passivelink-webui/gateway.env"
echo "Show it with: sudo sed -n 's/^DANTHERM_CONTROLLER_TOKEN=//p' /etc/dantherm-passivelink-webui/gateway.env"
echo "Rollback backup: ${backup}"
