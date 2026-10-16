#!/usr/bin/env bash
# Installs p4n4-hwd as a systemd service on a Raspberry Pi 5, running as the current user
# from this checkout. Run it as that user, not root: it uses sudo for the system steps.
#
#   scripts/rpi5/install-hwd.sh [--shutdown]
#
# --shutdown also adds the sudoers rule that lets a long press power the Pi off.
# Settings go in /etc/p4n4/hwd.env (created from systemd/hwd.env.example when missing).
# Re-running it updates the service; the settings file is kept.
set -euo pipefail

usage() { sed -n '2,10s/^# \{0,1\}//p' "$0"; }

shutdown_rule=false
for arg in "$@"; do
  case "$arg" in
    --shutdown) shutdown_rule=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $EUID -eq 0 ]]; then
  echo "Run this as the user the daemon runs as, not as root (it uses sudo itself)." >&2
  exit 1
fi

scripts=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
user=$(id -un)
venv=${P4N4_HW_VENV:-$HOME/.venvs/p4n4-hw}
unit=/etc/systemd/system/p4n4-hwd.service
env_file=/etc/p4n4/hwd.env

step() { echo "==> $*"; }

step "Installing rpi-lgpio (RPi.GPIO for the Pi 5) and venv support"
sudo apt-get install -y python3-rpi-lgpio python3-venv

step "Creating $venv with paho-mqtt"
python3 -m venv --system-site-packages "$venv"
"$venv/bin/pip" install --quiet "paho-mqtt>=2"

for group in gpio docker; do
  if getent group "$group" >/dev/null && ! id -nG "$user" | tr ' ' '\n' | grep -qx "$group"; then
    step "Adding $user to the $group group"
    sudo usermod -aG "$group" "$user"
  fi
done
getent group docker >/dev/null || echo "    (No docker group: the double-press restart needs Docker.)"

if [[ ! -e $env_file ]]; then
  step "Creating $env_file"
  sudo install -D -m 0600 -o root -g root "$scripts/systemd/hwd.env.example" "$env_file"
else
  step "Keeping $env_file"
fi

if $shutdown_rule; then
  rule=/etc/sudoers.d/p4n4-shutdown
  step "Allowing $user to run shutdown without a password ($rule)"
  tmp=$(mktemp)
  echo "$user ALL=(root) NOPASSWD: /usr/sbin/shutdown" > "$tmp"
  sudo visudo -cqf "$tmp"
  sudo install -m 0440 -o root -g root "$tmp" "$rule"
  rm -f "$tmp"
fi

step "Installing $unit"
sed -e "s|@USER@|$user|g" -e "s|@PYTHON@|$venv/bin/python|g" -e "s|@SCRIPTS@|$scripts|g" \
  "$scripts/systemd/p4n4-hwd.service" | sudo tee "$unit" >/dev/null

for script in p4n4_health_monitor p4n4_button_handler p4n4_mqtt_indicator; do
  if pgrep -f "$script.py" >/dev/null; then
    echo "    $script.py is running: stop it, it drives the same GPIO pins as the daemon."
  fi
done

step "Starting p4n4-hwd"
sudo systemctl daemon-reload
sudo systemctl enable p4n4-hwd
sudo systemctl restart p4n4-hwd  # starts it, or picks up a changed unit on a re-run

echo
echo "Done. Logs: journalctl -u p4n4-hwd -f    Settings: sudo nano $env_file"
