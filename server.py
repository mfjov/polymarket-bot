"""
Servidor web: sirve el dashboard HTML y expone /api/data con el estado actual.
Railway lo inicia automáticamente junto al cron del bot.
"""

import json
import os
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

DATA_FILE = Path("data/trades.json")
PORT      = int(os.environ.get("PORT", 8080))

INITIAL_BALANCE = 1000.0

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/api/data":
            self.serve_data()
        elif self.path == "/" or self.path == "/index.html":
            self.serve_file("dashboard.html", "text/html")
        else:
            self.send_error(404)

    def serve_data(self):
        if DATA_FILE.exists():
            with open(DATA_FILE) as f:
                data = json.load(f)
        else:
            data = {"balance": INITIAL_BALANCE, "trades": [], "equity_curve": [], "runs": []}
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, filename, content_type):
        path = Path(filename)
        if not path.exists():
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    print(f"Dashboard en http://localhost:{PORT}")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
