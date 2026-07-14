"""Wi-Fi nmcli parsers + camera-source toggle override."""
from acs.config import Config
from acs.core.camera import open_camera
from acs.core.wifi import local_ip, parse_current_ssid, parse_wifi_list


def test_parse_wifi_list_dedupes_drops_hidden_sorts():
    out = "HomeNet:72:*\nHomeNet:40:\nCafe:55:\n:30:\nGuest:88:"
    nets = parse_wifi_list(out)
    ssids = [n["ssid"] for n in nets]
    assert "" not in ssids                         # hidden/blank SSID dropped
    assert set(ssids) == {"HomeNet", "Cafe", "Guest"}
    home = next(n for n in nets if n["ssid"] == "HomeNet")
    assert home["in_use"] is True and home["signal"] == 72   # strongest + in-use kept
    assert nets[0]["ssid"] == "HomeNet"            # connected network sorts first


def test_parse_current_ssid():
    assert parse_current_ssid("yes:HomeNet\nno:Cafe") == "HomeNet"
    assert parse_current_ssid("no:Cafe\nno:Guest") is None


def test_local_ip_is_dotted_quad():
    ip = local_ip()
    assert isinstance(ip, str) and ip.count(".") == 3


def test_camera_source_override_wins_over_config():
    # config says 'auto' but the explicit source must win — and 'mock' never opens hardware
    cam = open_camera(Config({"camera": {"source": "auto"}}, "."), source="mock")
    assert type(cam).__name__ == "_MockCamera"
