"""Private persistent Python bridge and trace delivery, owned by tracking serve."""

import argparse
import http.server
import json
from pathlib import Path
import signal
import socketserver
import threading

from .cli import api
from .trace_delivery import flush


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def serve(home):
    home = Path(home).resolve()
    socket = home / ".godel/api.sock"
    socket.unlink(missing_ok=True)
    stopped = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 64 * 1024 * 1024:
                    raise ValueError("Invalid request size.")
                data = json.loads(self.rfile.read(length))
                if data["action"] == "run":
                    raise ValueError("Experiments use the cancellable subprocess bridge.")
                value = api(home, data["project"], data["action"], data.get("payload", {}))
                response = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(200)
            except Exception as error:
                response = json.dumps({"error": str(error)}).encode()
                self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = Server(str(socket), Handler)
    socket.chmod(0o600)
    server.timeout = 0.2

    def stop(*_):
        stopped.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)

    def deliver():
        while not stopped.is_set():
            try:
                flush(home)
            except Exception:
                # The queue remains durable; failed rows expose their errors.
                # Unexpected failures must not terminate the request server.
                import traceback

                traceback.print_exc()
            stopped.wait(0.1)

    worker = threading.Thread(target=deliver, daemon=True)
    worker.start()
    try:
        while not stopped.is_set():
            server.handle_request()
    finally:
        server.server_close()
        worker.join(timeout=12)
        socket.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    serve(parser.parse_args().home)
