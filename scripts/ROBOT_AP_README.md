Robot AP connection & diagnostics

Overview
- These helpers are for on-site operators to connect a node (e.g., `pi5`) to the robot's Wi‑Fi Access Point (AP) and to run quick network diagnostics.

Files
- `scripts/robot_connect_ap.sh` — connect to robot AP (uses `nmcli` if present, falls back to `wpa_supplicant`). Assigns a static IP (default `192.168.2.200/24`).
- `scripts/robot_network_diag.sh` — diagnostics: interfaces, routes, ping, traceroute, TCP probe, ARP table.

Quick steps
1. On the node (pi5), run:
   sudo ./scripts/robot_connect_ap.sh ROBOT_SSID ROBOT_PSK
2. Verify ping: `ping -c3 192.168.2.1`
3. If ping fails, run diagnostics:
   sudo ./scripts/robot_network_diag.sh

Notes
- These scripts require `sudo` to configure interfaces and may modify network connectivity (they assign a static IP to the wireless interface).
- After testing, restore normal network state (e.g., re-enable NetworkManager connection or reboot) to return to usual network.
