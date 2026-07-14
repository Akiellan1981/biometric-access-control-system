"""Run the dashboard with MediaPipe's native log spam silenced.

Use this instead of calling uvicorn directly:

    python serve.py                 # uses web.host / web.port from config.yaml
    ACS_HOST=0.0.0.0 python serve.py   # override host (LAN)
    ACS_PORT=9000 python serve.py      # override port

The order matters: we redirect native stderr FIRST, then import uvicorn, so
uvicorn's logging binds to the preserved terminal while the C++ noise goes to
null. Set ACS_QUIET_NATIVE=0 to see the native logs again.
"""
from acs.core.quiet import silence_native_stderr

silence_native_stderr()

import os  # noqa: E402
import socket  # noqa: E402

import uvicorn  # noqa: E402

from acs.config import Config  # noqa: E402


def _silence_win_conn_reset():
    """Windows-only cosmetic fix: the Proactor event loop logs a harmless
    ConnectionResetError (WinError 10054) when a browser abruptly drops a
    connection (e.g. closing the live /camera/stream). Swallow it so the console
    stays clean. No-op on Linux (the Pi), which never hits this path."""
    import platform
    if platform.system() != "Windows":
        return
    try:
        import asyncio.proactor_events as pe
        _orig = pe._ProactorBasePipeTransport._call_connection_lost

        def _patched(self, exc):
            try:
                _orig(self, exc)
            except (ConnectionResetError, ConnectionAbortedError):
                pass
        pe._ProactorBasePipeTransport._call_connection_lost = _patched
    except Exception:  # noqa: BLE001 - never let a cosmetic patch break startup
        pass


def _port_in_use(host: str, port: int) -> bool:
    target = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((target, port)) == 0


if __name__ == "__main__":
    cfg = Config.load()
    host = os.environ.get("ACS_HOST", cfg.get("web.host", "127.0.0.1"))
    port = int(os.environ.get("ACS_PORT", cfg.get("web.port", 8010)))

    # A stale server already on this port would keep serving OLD code while this
    # (new) one silently fails to bind — refuse to start and say so clearly.
    if _port_in_use(host, port):
        raise SystemExit(
            f"\nERROR: port {port} is already in use — another AEGIS server is running.\n"
            f"Stop it (close that window / Ctrl+C), or kill it:\n"
            f"  PowerShell:  Get-NetTCPConnection -LocalPort {port} -State Listen | "
            f"%{{ Stop-Process -Id $_.OwningProcess -Force }}\n"
            f"…then run 'python serve.py' again (or change web.port in config.yaml).\n")

    from acs.core.preflight import production_warnings
    from acs.storage.crypto import TemplateCipher
    _cipher = TemplateCipher(cfg.path("paths.key_file"))
    for _w in production_warnings(cfg, _cipher.enabled):
        print(f"PREFLIGHT WARNING: {_w}")

    _silence_win_conn_reset()
    print(f"AEGIS dashboard -> http://{'127.0.0.1' if host in ('127.0.0.1','0.0.0.0') else host}:{port}")
    try:
        uvicorn.run("acs.web.app:app", host=host, port=port)
    except KeyboardInterrupt:
        print("\nAEGIS dashboard stopped.")   # clean Ctrl+C exit (no traceback)
