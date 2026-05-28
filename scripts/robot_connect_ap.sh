#!/usr/bin/env bash
set -euo pipefail

# robot_connect_ap.sh
# Connect the host (pi5) to the robot's Wi-Fi AP and assign a static IP
# Usage: sudo ./scripts/robot_connect_ap.sh SSID PSK [INTERFACE] [STATIC_IP]

SSID=${1:-}
PSK=${2:-}
IFACE=${3:-wlan0}
STATIC_IP=${4:-192.168.2.200/24}

if [ -z "$SSID" ] || [ -z "$PSK" ]; then
  echo "Usage: sudo $0 SSID PSK [INTERFACE] [STATIC_IP]"
  exit 2
fi

echo "Connecting interface $IFACE to SSID='$SSID'"

if command -v nmcli >/dev/null 2>&1; then
  echo "Using nmcli..."
  sudo nmcli device wifi connect "$SSID" password "$PSK" ifname "$IFACE" || true
  # give it a moment to associate
  sleep 3
  echo "Assigning static IP $STATIC_IP to $IFACE"
  sudo ip addr flush dev "$IFACE" || true
  sudo ip addr add "$STATIC_IP" dev "$IFACE"
  sudo ip link set "$IFACE" up
else
  echo "nmcli not found; falling back to wpa_supplicant method"
  TMP_CONF=/tmp/wpa_${IFACE}.conf
  cat > "$TMP_CONF" <<EOF
ctrl_interface=/run/wpa_supplicant
network={
  ssid="$SSID"
  psk="$PSK"
  key_mgmt=WPA-PSK
}
EOF
  sudo pkill -f "wpa_supplicant -i$IFACE" || true
  sudo wpa_supplicant -B -i "$IFACE" -c "$TMP_CONF" || true
  sleep 3
  sudo ip addr flush dev "$IFACE" || true
  sudo ip addr add "$STATIC_IP" dev "$IFACE"
  sudo ip link set "$IFACE" up
fi

echo "Checking connectivity to robot (192.168.2.1)"
ping -c 3 192.168.2.1 || true
echo "Done. If ping fails, verify robot is powered on and broadcasting AP."
