"""
Servidor web con scheduler integrado.
Corre bot.py cada hora en un thread separado, comparte el mismo filesystem.
"""
import json
import os
import logging
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
import scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DATA_FILE = Path("data/trades.json")
PORT      = int(os.environ.get("PORT", 8080))
INITIAL_BALANCE = 1000.0

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args): pass

    def do_GET(self):
        if self.path == "/api/data": self.serve_data()
        elif self.path in ("/", "/index.html"): self.serve_file("dashboard.html", "text/html")
        else: self.send_error(404)

    def serve_data(self):
        if DATA_FILE.exists():
            with open(DATA_FILE) as f: data = json.load(f)
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
        if not path.exists(): self.send_error(404); return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

if __name__ == "__main__":
    interval = int(os.environ.get("BOT_INTERVAL_SECONDS", 3600))
    scheduler.start(interval_seconds=interval)
    print(f"Dashboard en http://localhost:{PORT}")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    server.serve_forever()
