# routes_debug.py (temporary)
import socket, ssl
from flask import Blueprint, current_app

bp = Blueprint("debug", __name__)

@bp.route("/_smtp_probe")
def smtp_probe():
    host = current_app.config.get("MAIL_SERVER")
    port = int(current_app.config.get("MAIL_PORT", "0"))
    use_ssl = str(current_app.config.get("MAIL_USE_SSL", "false")).lower() in {"1","true","t","yes","y","on"}
    if not host or not port:
        return "Set MAIL_SERVER and MAIL_PORT first", 400

    try:
        addr = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        # try connect
        raw = socket.create_connection((host, port), timeout=5)
        if use_ssl:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(raw, server_hostname=host) as s:
                s.recv(64)  # banner
        else:
            raw.recv(64)
        return f"OK: connected to {host}:{port}"
    except Exception as e:
        return f"FAIL: {host}:{port} -> {e}", 500
