#!/usr/bin/env bash
set -euo pipefail

# robot_network_diag.sh
# Quick diagnostics for robot network reachability
# Usage: sudo ./scripts/robot_network_diag.sh [ROBOT_IP] [PORT]

ROBOT_IP=${1:-192.168.2.1}
PORT=${2:-40922}

echo "=== Interfaces ==="
ip addr show
echo
echo "=== Routes ==="
ip route
echo
echo "=== Ping ${ROBOT_IP} ==="
ping -c 5 "$ROBOT_IP" || true
echo
echo "=== Traceroute to ${ROBOT_IP} (may require sudo) ==="
if command -v traceroute >/dev/null 2>&1; then
  traceroute -n "$ROBOT_IP" || true
else
  echo "traceroute not available"
fi
echo
echo "=== TCP probe ${ROBOT_IP}:${PORT} ==="
if command -v nc >/dev/null 2>&1; then
  echo | nc -vz "$ROBOT_IP" "$PORT" || true
else
  echo "nc (netcat) not available"
fi
echo
echo "=== ARP table ==="
ip neigh show

echo "Done."
