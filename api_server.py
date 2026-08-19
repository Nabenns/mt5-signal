"""
Signal Relay API — RESTful endpoints for MT5 trade management.
Run: python3 -m http.server 8080 --directory . (or use this as module)

ENDPOINTS:
- GET /api/health       → Health check & stats
- GET /api/positions    → Active positions
- POST /api/positions   → Open new position (mock/simulation)
- DELETE /api/positions/{position_id} → Close position
- POST /api/signal      → Legacy webhook endpoint (passthrough to MT5 EA)
- GET /api/logs         → Recent logs (last 100 entries)
- GET /api/state        → Raw state JSON
- PUT /api/reset        → Reset system (clear all locks/pending)
"""

import json
import os
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import queue

BASE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE, ".env")

# Load environment
ENV = {}
with open(ENV_FILE) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip()

SECRET = ENV["RECEIVER_SECRET"]
PORT = int(ENV.get("PORT", "8080"))  # API port
MT5_API_URL = ENV.get("MT5_API_URL", "http://localhost:8080")

# Thread-safe state storage
_lock = threading.Lock()
state_data = {"active": {}, "pending": {}}
logs = queue.Queue(maxsize=200)

def log(msg):
    """Add log entry."""
    try:
        logs.put(f"[{datetime.now().isoformat()}] {msg}", block=False)
    except queue.Full:
        pass

def save_state():
    """Persist state to disk."""
    tmp = os.path.join(BASE, "state.json.tmp")
    with open(tmp, "w") as f:
        json.dump(state_data, f, indent=2)
    try:
        os.replace(tmp, os.path.join(BASE, "state.json"))
    except OSError:
        pass

def load_state():
    """Load state from disk."""
    global state_data
    try:
        with open(os.path.join(BASE, "state.json")) as f:
            state_data = json.load(f)
    except (OSError, ValueError):
        state_data = {"active": {}, "pending": {}}

# Initialize state
load_state()


class SignalAPIHandler(BaseHTTPRequestHandler):
    """REST API request handler."""

    def send_json(self, code, data):
        body = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def get_auth(self):
        """Extract bearer token or secret from headers/query."""
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        qs = parse_qs(urlparse(self.path).query)
        return qs.get("secret", [None])[0]

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, PUT")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/health":
            # Health check
            with _lock:
                st = {**state_data}
            self.send_json(200, {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "port": PORT,
                "stats": {
                    "active_positions": len(st.get("active", {})),
                    "pending_orders": len(st.get("pending", {})),
                    "locked_symbol_count": len([k for k in st.get("active", {}).keys()]),
                }
            })

        elif path == "/api/positions":
            # List active positions
            with _lock:
                st = {**state_data}
            positions = []
            for symbol, pos_info in st.get("active", {}).items():
                positions.append({
                    "symbol": symbol,
                    "position_id": pos_info.get("position"),
                    "price": pos_info.get("price"),
                    "opened_at": pos_info.get("ts"),
                    "status": "active"
                })
            self.send_json(200, {
                "count": len(positions),
                "data": positions
            })

        elif path == "/api/logs":
            # Recent logs
            limit = 50
            try:
                n = int(parse_qs(parsed.query).get("limit", ["50"])[0])
            except ValueError:
                n = 50
            entries = []
            while not logs.empty() and len(entries) < n:
                entries.insert(0, logs.get_nowait())
            self.send_json(200, {
                "count": len(entries),
                "data": entries
            })

        elif path == "/api/state":
            # Raw state (use with caution!)
            with _lock:
                st = {**state_data}
            self.send_json(200, st)

        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/signal":
            # Legacy webhook: passthrough to internal logic
            self._handle_signal_endpoint()

        elif path == "/api/reset":
            # System reset — requires auth
            if not self._check_auth():
                return self.send_json(401, {"error": "Unauthorized"})
            
            with _lock:
                global state_data
                state_data = {"active": {}, "pending": {}}
                logs.queue.clear()
            save_state()
            log("System reset via API")
            self.send_json(200, {"status": "reset complete"})

        else:
            self.send_json(404, {"error": "Not found"})

    def _handle_signal_endpoint(self):
        """Handle incoming signal requests from MT5 EA."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            req = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json(400, {"error": "Invalid JSON"})

        action = (req.get("action") or "").upper()

        if action == "OPEN":
            # Check lock per symbol
            symbol = req.get("symbol")
            sl = float(req.get("sl") or 0)
            tp = float(req.get("tp") or 0)
            now = time.time()
            
            with _lock:
                # Lock check
                act = state_data.get("active", {}).get(symbol)
                if act and (now - act.get("ts", 0)) < 86400:
                    log(f"SUPPRESS {symbol}: position {act.get('position')} still active")
                    return self.send_json(200, {"status": "suppressed", "reason": "position_active"})

                # Entry with SL & TP -> immediate send
                if sl > 0 or tp > 0:
                    # Enqueue signals (would go to Telegram via selfbot)
                    state_data.setdefault("active", {})[symbol] = {
                        "position": req.get("position"),
                        "ts": now,
                        "price": req.get("price"),
                    }
                    log(f"SENT COMPLETE: {req.get('type')} {symbol} SL={sl} TP={tp}")
                    save_state()
                    return self.send_json(200, {"status": "sent", "merged": True})

                # No SL/TP -> hold pending
                deal = req.get("deal") or req.get("position")
                key = f"{symbol}:{deal}"
                state_data.setdefault("pending", {})[key] = {
                    "symbol": symbol,
                    "type": req.get("type"),
                    "price": req.get("price"),
                    "sl": sl,
                    "tp": tp,
                    "deadline": now + 120,
                }
                save_state()
                log(f"HOLD {symbol} — waiting for SL & TP")
                return self.send_json(200, {"status": "holding"})

        elif action == "SLTP":
            symbol = req.get("symbol")
            position = req.get("position")
            sl = float(req.get("sl") or 0)
            tp = float(req.get("tp") or 0)

            with _lock:
                matched_key = None
                for key, pend in state_data.get("pending", {}).items():
                    if pend.get("symbol") != symbol:
                        continue
                    if ((req.get("deal") or 0) > 0 and pend.get("deal") == req.get("deal")) or \
                       (position > 0 and pend.get("position") == position):
                        matched_key = key
                        break

                if not matched_key:
                    return self.send_json(200, {"status": "ignored", "reason": "no_pending_entry"})

                pend = state_data["pending"][matched_key]
                if sl > 0:
                    pend["sl"] = sl
                if tp > 0:
                    pend["tp"] = tp

                if not (pend["sl"] > 0 and pend["tp"] > 0):
                    return self.send_json(200, {"status": "holding_partial"})

                del state_data["pending"][matched_key]
                state_data.setdefault("active", {})[symbol] = {
                    "position": position,
                    "ts": time.time(),
                    "price": pend.get("price"),
                }
                save_state()
                log(f"SENT COMPLETE: {pend.get('type')} {symbol}")
                return self.send_json(200, {"status": "sent", "merged": True})

        elif action == "CLOSE":
            position = req.get("position")
            with _lock:
                active = state_data.get("active", {})
                for symbol, info in list(active.items()):
                    if info.get("position") == position:
                        del active[symbol]
                        log(f"CLOSE {symbol} — lock released")
                        break
                save_state()
            return self.send_json(200, {"status": "closed"})

        else:
            return self.send_json(200, {"status": "skipped"})

    def _check_auth(self):
        """Check authentication."""
        token = self.get_auth()
        return token == SECRET

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def main():
    print(f"Signal Relay API v2 — Running on port {PORT}")
    print(f"Endpoints:")
    print(f"  GET  /api/health      → Health check")
    print(f"  GET  /api/positions   → Active positions")
    print(f"  GET  /api/logs?limit=50 → Recent logs")
    print(f"  GET  /api/state       → Raw state")
    print(f"  POST /api/signal      → Webhook from MT5 EA")
    print(f"  POST /api/reset       → Reset system (requires auth)")
    
    server = HTTPServer(("127.0.0.1", PORT), SignalAPIHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
