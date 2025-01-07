import json  # noqa: D100
import logging
import socket
from typing import Any

from process_pilot.pilot import ProcessPilot
from process_pilot.plugin import ControlServerType, Plugin


class TCPControlServer:
    """TCP server that provides remote control capabilities for ProcessPilot instances."""

    def __init__(self, pilot: ProcessPilot, host: str = "localhost", port: int = 9999) -> None:
        """
        Initialize the TCP control server.

        Args:
            pilot: The ProcessPilot instance to control.
            host: The host address to bind to.
            port: The port number to listen on.

        """
        self.pilot = pilot
        self.host = host
        self.port = port
        self._socket: socket.socket | None = None
        self._running = False

    def start(self) -> None:
        """Start the TCP control server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind((self.host, self.port))
        self._socket.listen()
        self._running = True
        self._run()

    def stop(self) -> None:
        """Stop the TCP control server."""
        self._running = False
        if self._socket:
            self._socket.close()

    def _run(self) -> None:
        while self._running:
            try:
                if not self._socket:
                    raise RuntimeError  # noqa: TRY301

                conn, _ = self._socket.accept()
                with conn:
                    data = conn.recv(1024).decode()
                    command = json.loads(data)
                    self._handle_command(command, conn)
            except Exception:
                if self._running:
                    logging.exception("Error in control server")

    def _handle_command(self, command: dict[str, Any], conn: socket.socket) -> None:
        try:
            match command["action"]:
                case "restart":
                    process_names = command.get("processes", [])
                    self.pilot.restart_processes(process_names)
                    response = {"status": "success"}
                case _:
                    response = {"status": "error", "message": "Unknown command"}
            conn.sendall(json.dumps(response).encode())
        except (KeyError, json.JSONDecodeError, OSError) as e:
            error_response = {"status": "error", "message": str(e)}
            conn.sendall(json.dumps(error_response).encode())


class TCPControlPlugin(Plugin):
    """Plugin that provides a TCP-based control server."""

    def get_control_servers(self) -> dict[str, ControlServerType]:
        """Return a dictionary mapping server names to their control server factory functions."""
        return {"tcp": lambda pilot: TCPControlServer(pilot)}
