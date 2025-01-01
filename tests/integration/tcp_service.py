import socket  # noqa: INP001


def start_tcp_service(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", port))
        s.listen()
        print(f"TCP service listening on port {port}")  # noqa: T201
        while True:
            conn, addr = s.accept()
            with conn:
                print(f"Connected by {addr}")  # noqa: T201
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    conn.sendall(data)


if __name__ == "__main__":
    start_tcp_service(9876)
