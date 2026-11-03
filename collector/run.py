"""Inicia o coletor e mostra os endereços para abrir no navegador e configurar o ESP32."""
import os
import socket

import uvicorn

HOST = os.environ.get("COLLECTOR_HOST", "0.0.0.0")
PORT = int(os.environ.get("COLLECTOR_PORT", "8765"))


def lan_ips() -> list[str]:
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return sorted({i[4][0] for i in infos if not i[4][0].startswith("127.")})


if __name__ == "__main__":
    print("=" * 60)
    print(f" Interface:  http://localhost:{PORT}")
    for ip in lan_ips():
        print(f" ESP32:      ws://{ip}:{PORT}/ws/device")
    print("=" * 60)
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")
