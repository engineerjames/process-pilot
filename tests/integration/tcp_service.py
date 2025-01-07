import logging  # noqa: INP001
import socket
import time

# ruff: noqa: F401, RUF100, T201, BLE001


def start_tcp_service(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        while True:
            try:
                logging.debug("Attempting to bind socket...")
                s.bind(("localhost", port))
                s.listen()
                break
            except Exception:
                logging.exception("Error connecting")

            time.sleep(1.0)

        print(f"TCP service listening on port {port}")  # noqa: T201
        while True:
            conn, addr = s.accept()
            with conn:
                logging.debug("Connected by %s", addr)  # noqa: T201
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    conn.sendall(data)


if __name__ == "__main__":
    start_tcp_service(9876)
