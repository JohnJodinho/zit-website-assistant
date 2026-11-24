from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.smoke_live import main


def test_smoke_script_runs_end_to_end_against_local_api(capsys) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/v1/config":
                self._respond(
                    200,
                    {"enabled": True},
                    {"Access-Control-Allow-Origin": self.headers.get("Origin", "")},
                )
                return
            self._respond(200, {"status": "ok"})

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/api/v1/sessions":
                self._respond(200, {"session_token": "local-smoke-session"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(
                b'event: delta\ndata: {"t":"Contact Admissions."}\n\n'
                b'event: done\ndata: {"finish":"stop"}\n\n'
            )

        def _respond(
            self,
            status: int,
            payload: dict[str, object],
            headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        result = main(
            [
                "--api",
                f"http://127.0.0.1:{server.server_port}",
                "--origin",
                "http://localhost:5173",
            ]
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert result == 0
    assert "PASS\tchat-stream" in capsys.readouterr().out
