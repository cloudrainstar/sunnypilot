"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import subprocess
import threading
import time

from openpilot.common.swaglog import cloudlog
from openpilot.system.ui.lib.wifi_manager import WifiManager

TETHERING_SUBNET = "192.168.43.0/24"
TETHERING_UPLINK_IFACE = "wwan0"
TETHERING_WIFI_IFACE = "wlan0"


class WifiManagerSP(WifiManager):
  def __init__(self):
    super().__init__()

  @staticmethod
  def _tethering_nat_rule() -> list[str]:
    return ["POSTROUTING", "-s", TETHERING_SUBNET, "-o", TETHERING_UPLINK_IFACE, "-j", "MASQUERADE"]

  def _has_tethering_nat_rule(self) -> bool:
    nat_rule = self._tethering_nat_rule()
    return subprocess.run(
      ["sudo", "iptables-legacy", "-t", "nat", "-C", *nat_rule],
      check=False,
    ).returncode == 0

  def _set_tethering_nat_rule(self, present: bool) -> None:
    nat_rule = self._tethering_nat_rule()
    exists = self._has_tethering_nat_rule()

    if present and not exists:
      subprocess.run(["sudo", "iptables-legacy", "-t", "nat", "-A", *nat_rule], check=False)
    elif not present and exists:
      subprocess.run(["sudo", "iptables-legacy", "-t", "nat", "-D", *nat_rule], check=False)

  def is_tethering_internet_shared(self) -> bool:
    return self._has_tethering_nat_rule()

  def set_tethering_internet_shared(self, shared: bool) -> None:
    self._set_tethering_nat_rule(shared and self._ipv4_forward)

  def set_tethering_wifi_compat_enabled(self, enabled: bool) -> None:
    if enabled and self.is_tethering_active():
      threading.Thread(target=self._set_tethering_ap_compatibility, daemon=True).start()

  def _get_tethering_network_id(self) -> str | None:
    result = subprocess.run(
      ["wpa_cli", "-i", TETHERING_WIFI_IFACE, "list_networks"],
      capture_output=True,
      text=True,
      check=False,
    )
    if result.returncode != 0:
      return None

    for line in result.stdout.splitlines()[1:]:
      fields = line.split("\t")
      if len(fields) >= 2 and fields[1] == self._tethering_ssid:
        return fields[0]

    return None

  def _set_tethering_ap_compatibility(self) -> None:
    time.sleep(3)
    network_id = self._get_tethering_network_id()
    if network_id is None:
      cloudlog.warning("Failed to find tethering wpa_supplicant network")
      return

    # Pixel 9a rejects this AP when wpa_supplicant advertises WPA-PSK-SHA256/RSNXE.
    for command in (
      ["wpa_cli", "-i", TETHERING_WIFI_IFACE, "set_network", network_id, "key_mgmt", "WPA-PSK"],
      ["wpa_cli", "-i", TETHERING_WIFI_IFACE, "set_network", network_id, "ieee80211w", "0"],
      ["wpa_cli", "-i", TETHERING_WIFI_IFACE, "disable_network", network_id],
    ):
      subprocess.run(command, check=False)
    time.sleep(2)
    subprocess.run(["wpa_cli", "-i", TETHERING_WIFI_IFACE, "enable_network", network_id], check=False)

  def set_tethering_active(self, active: bool):
    super().set_tethering_active(active)
    if not active:
      self._set_tethering_nat_rule(False)
