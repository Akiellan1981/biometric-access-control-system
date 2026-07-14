"""Wi-Fi management for the dashboard.

On the Raspberry Pi (Linux + NetworkManager) this drives `nmcli` to scan and join
networks. On any other OS (e.g. the Windows dev PC) it degrades to a safe mock:
it still reports the device IP (so you know the URL to open the live feed) but
reports Wi-Fi control as unavailable.

Subprocess calls pass arguments as a list (never a shell string) so an SSID or
password can't inject a command.
"""
from __future__ import annotations

import platform
import shutil
import socket
import subprocess


def local_ip() -> str:
    """Best-effort LAN IP of this device (works on Windows + Linux)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


def nmcli_available() -> bool:
    return platform.system() == "Linux" and shutil.which("nmcli") is not None


def parse_wifi_list(output: str) -> list[dict]:
    """Parse `nmcli -t -f SSID,SIGNAL,IN-USE device wifi list` (colon-separated).
    Returns [{ssid, signal, in_use}] deduped by SSID (strongest signal kept)."""
    best: dict[str, dict] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":")
        ssid = parts[0].strip()
        if not ssid:                       # hidden networks have no SSID
            continue
        try:
            signal = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 0
        except ValueError:
            signal = 0
        in_use = len(parts) > 2 and parts[2].strip() == "*"
        cur = best.get(ssid)
        if cur is None or signal > cur["signal"] or in_use:
            best[ssid] = {"ssid": ssid, "signal": signal, "in_use": in_use}
    return sorted(best.values(), key=lambda n: (-int(n["in_use"]), -n["signal"]))


def parse_current_ssid(output: str) -> str | None:
    """Parse `nmcli -t -f active,ssid device wifi` -> the active SSID, or None."""
    for line in output.splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 2 and parts[0].strip() == "yes":
            return parts[1].strip() or None
    return None


class WifiManager:
    def __init__(self):
        self.available = nmcli_available()

    def status(self) -> dict:
        ssid = None
        if self.available:
            try:
                out = subprocess.run(["nmcli", "-t", "-f", "active,ssid", "device", "wifi"],
                                     capture_output=True, text=True, timeout=5).stdout
                ssid = parse_current_ssid(out)
            except Exception:  # noqa: BLE001
                ssid = None
        return {"available": self.available, "ip": local_ip(), "ssid": ssid}

    def scan(self) -> list[dict]:
        if not self.available:
            return []
        try:
            subprocess.run(["nmcli", "device", "wifi", "rescan"],
                           capture_output=True, text=True, timeout=10)
            out = subprocess.run(["nmcli", "-t", "-f", "SSID,SIGNAL,IN-USE", "device", "wifi", "list"],
                                 capture_output=True, text=True, timeout=10).stdout
            return parse_wifi_list(out)
        except Exception:  # noqa: BLE001
            return []

    def connect(self, ssid: str, password: str) -> tuple[bool, str]:
        ssid = (ssid or "").strip()
        if not ssid:
            return False, "Pick a network."
        if not self.available:
            return False, ("Wi-Fi control is only available on the Raspberry Pi. "
                           "Set it via raspi-config / nmcli on the device.")
        cmd = ["nmcli", "device", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]          # args list -> no shell injection
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return True, f"Connected to {ssid}. The device IP may have changed — see below."
            return False, (r.stderr or r.stdout or "connection failed").strip()
        except Exception as e:  # noqa: BLE001
            return False, str(e)
