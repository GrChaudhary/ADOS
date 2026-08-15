"""P11 follow-up — a minimal local receiver for Alertmanager's webhook
integration (infrastructure/prometheus/alertmanager.yml). Binds 127.0.0.1
only; logs every delivered payload to stdout and appends it as one JSON line
to webhook_receiver.log next to this file, so a scrape/alert/delivery proof
run can be inspected after the fact rather than only trusted live.

This is a development/verification tool, not a real alert destination — see
docs/prime-agent-integration/22-metrics-alerting-operationalization.md.
Run directly: python infrastructure/prometheus/webhook_receiver.py [port]
"""

import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "webhook_receiver.log"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received_at = datetime.now(timezone.utc).isoformat()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body.decode("utf-8", errors="replace")}

        record = {"received_at": received_at, "path": self.path, "payload": payload}
        print(f"[webhook_receiver] {received_at} {self.path} status={payload.get('status')} "
              f"alerts={[a.get('labels', {}).get('alertname') for a in payload.get('alerts', [])]}")
        with LOG_PATH.open("a") as f:
            f.write(json.dumps(record) + "\n")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"received"}')

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        pass  # replaced by the structured print() above


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9095
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[webhook_receiver] listening on http://127.0.0.1:{port} (local only), logging to {LOG_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
