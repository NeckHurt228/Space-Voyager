#!/usr/bin/env python3
"""
niche_app.py - the Niche Finder app. Opens in your browser, runs on your computer.

    python3 tools/niche_app.py          # or double-click "Niche Finder.command" (Mac) / "Niche Finder.bat" (Windows)
    python3 tools/niche_app.py --demo   # try the app with made-up sample data, no API key needed

Nothing leaves your computer except calls to the YouTube API. Your API key is saved in
reports/niches/settings.json (that folder is not committed to git).
Only Python 3 is required. For the faceless check also run: pip install "opencv-python-headless<5"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import niche_finder as nf  # noqa: E402

UI_FILE = HERE / "niche_app" / "index.html"
ROOT = HERE.parent

DEFAULTS = {
    "api_key": "",
    "min_views": 10_000_000,
    "days": 7,
    "max_channel_age": 30,
    "regions": ["US"],
    "faceless_only": False,
    "quota_budget": 9000,
    "pages": 1,
    "seeds": [],
}


class Stopped(nf.QuotaExhausted):
    pass


class StoppableAPI(nf.YouTubeAPI):
    def __init__(self, *a, stop: threading.Event, **kw):
        super().__init__(*a, **kw)
        self.stop = stop

    def get(self, endpoint, **params):
        if self.stop.is_set():
            raise Stopped("stopped by you; showing what was found so far")
        return super().get(endpoint, **params)


class App:
    def __init__(self, out: Path, demo: bool):
        self.out = out
        self.demo = demo
        self.out.mkdir(parents=True, exist_ok=True)
        self.settings_path = out / "settings.json"
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.run = {"running": False, "stage": 0, "stage_label": "", "log": [], "quota_used": 0,
                    "quota_budget": 0, "error": "", "result": "", "stopped": False}

    # ---------------- settings
    def settings(self) -> dict:
        s = dict(DEFAULTS)
        s["seeds"] = nf.load_seeds(nf.DEFAULT_SEEDS)
        if self.settings_path.exists():
            try:
                s.update(json.loads(self.settings_path.read_text()))
            except json.JSONDecodeError:
                pass
        if not s["api_key"]:
            s["api_key"] = os.environ.get("YOUTUBE_API_KEY", "")
        return s

    def save_settings(self, new: dict):
        s = self.settings()
        for k in DEFAULTS:
            if k in new and k != "api_key":
                s[k] = new[k]
        if new.get("api_key"):
            s["api_key"] = new["api_key"].strip()
        if new.get("clear_key"):
            s["api_key"] = ""
        s["regions"] = [r for r in s["regions"] if re.fullmatch(r"[A-Z]{2}", r)] or ["US"]
        s["seeds"] = [q.strip() for q in s["seeds"] if isinstance(q, str)][:200]
        self.settings_path.write_text(json.dumps(s, indent=2))
        try:
            os.chmod(self.settings_path, 0o600)
        except OSError:
            pass
        return s

    def public_settings(self) -> dict:
        s = self.settings()
        key = s.pop("api_key")
        s["has_key"] = bool(key) or self.demo
        s["key_hint"] = ("…" + key[-4:]) if key else ""
        return s

    # ---------------- runs
    def runs(self) -> list[dict]:
        out = []
        for f in sorted(self.out.glob("niches_*.json"), reverse=True)[:30]:
            try:
                d = json.loads(f.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            out.append({"stamp": f.stem[len("niches_"):], "generated": d["meta"]["generated"],
                        "channels": len(d["channels"]), "niches": len(d["niches"]),
                        "min_views": d["meta"]["min_views"], "demo": d["meta"].get("demo", False)})
        return out

    def state(self) -> dict:
        with self.lock:
            run = dict(self.run, log=self.run["log"][-200:])
        return {"settings": self.public_settings(), "run": run, "runs": self.runs(), "demo": self.demo}

    def test_key(self, key: str) -> tuple[bool, str]:
        if self.demo:
            return True, "Demo mode: no key needed."
        key = key or self.settings()["api_key"]
        if not key:
            return False, "Paste your API key first."
        try:
            nf.YouTubeAPI(key, budget=5).get("videoCategories", part="snippet", regionCode="US")
            return True, "Connected. Your key works."
        except SystemExit as e:
            msg = str(e)
            if "(400" in msg or "keyInvalid" in msg or "API key not valid" in msg:
                return False, "That key isn't valid. Copy it again from Google Cloud → Credentials (step 3)."
            if "(403" in msg:
                return False, ("Google refused this key. Make sure YouTube Data API v3 is enabled for the "
                               "same project (step 2), then try again in a minute.")
            return False, msg.split("\n")[0]
        except Exception as e:  # network trouble etc.
            return False, f"Could not reach YouTube: {e}"

    def start(self) -> tuple[bool, str]:
        with self.lock:
            if self.run["running"]:
                return False, "A search is already running."
            s = self.settings()
            if not s["api_key"] and not self.demo:
                return False, "Add your YouTube API key first."
            self.stop.clear()
            self.run = {"running": True, "stage": 0, "stage_label": "Starting", "log": [], "quota_used": 0,
                        "quota_budget": s["quota_budget"], "error": "", "result": "", "stopped": False}
        threading.Thread(target=self._work, args=(s,), daemon=True).start()
        return True, "started"

    def _log(self, *parts):
        line = " ".join(str(p) for p in parts).strip()
        with self.lock:
            self.run["log"].append(line)
            if self._api:
                self.run["quota_used"] = self._api.used

    def _stage(self, n, label):
        with self.lock:
            self.run["stage"], self.run["stage_label"] = n, label
            if self._api:
                self.run["quota_used"] = self._api.used

    _api = None

    def _work(self, s: dict):
        try:
            args = nf.build_parser().parse_args([
                "--out", str(self.out), "--min-views", str(s["min_views"]), "--days", str(s["days"]),
                "--max-channel-age", str(s["max_channel_age"]), "--regions", ",".join(s["regions"]),
                "--quota-budget", str(s["quota_budget"]), "--pages", str(s["pages"]), "--quiet"]
                + (["--faceless-only"] if s["faceless_only"] else []))
            args.seed_list = s["seeds"] or ["(blank)"]
            args.seed_list = ["" if q == "(blank)" else q for q in args.seed_list]
            if self.demo:
                import test_niche_finder as demo
                api = demo.FakeAPI()
                api.stop = self.stop
                args.faceless = "off"
            else:
                api = StoppableAPI(s["api_key"], s["quota_budget"], stop=self.stop)
            self._api = api
            res = nf.pipeline(api, args, log=self._log, on_stage=self._stage)
            if self.demo:  # mark demo results so they're never mistaken for real ones
                p = Path(res["json"])
                d = json.loads(p.read_text())
                d["meta"]["demo"] = True
                p.write_text(json.dumps(d, indent=2))
            with self.lock:
                self.run["result"] = res["stamp"]
                self.run["stopped"] = self.stop.is_set()
                self.run["quota_used"] = api.used
        except SystemExit as e:
            with self.lock:
                self.run["error"] = str(e).split("\n")[0]
        except Exception as e:
            traceback.print_exc()
            with self.lock:
                self.run["error"] = f"Something went wrong: {e}"
        finally:
            with self.lock:
                self.run["running"] = False
            self._api = None

    def result(self, stamp: str) -> dict | None:
        if not re.fullmatch(r"[0-9_-]+", stamp):
            return None
        f = self.out / f"niches_{stamp}.json"
        return json.loads(f.read_text()) if f.exists() else None

    def report_file(self, name: str) -> Path | None:
        if not re.fullmatch(r"niches_[0-9_-]+\.(html|csv)", name):
            return None
        f = self.out / name
        return f if f.exists() else None


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode())

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode())
            except json.JSONDecodeError:
                return {}

        def _same_origin(self) -> bool:
            # block other websites from driving this local app
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            return origin is None or origin.split("://", 1)[-1] == host

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(app.state())
            if path.startswith("/api/result/"):
                d = app.result(path.rsplit("/", 1)[-1])
                return self._json(d) if d else self._json({"error": "not found"}, 404)
            if path.startswith("/files/"):
                f = app.report_file(path.rsplit("/", 1)[-1])
                if not f:
                    return self._json({"error": "not found"}, 404)
                ctype = "text/html; charset=utf-8" if f.suffix == ".html" else "text/csv"
                extra = {"Content-Disposition": f'attachment; filename="{f.name}"'} if f.suffix == ".csv" else None
                return self._send(200, f.read_bytes(), ctype, extra)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._same_origin():
                return self._json({"error": "forbidden"}, 403)
            path = self.path.split("?", 1)[0]
            body = self._body()
            if path == "/api/settings":
                app.save_settings(body)
                return self._json(app.state())
            if path == "/api/test-key":
                if body.get("api_key"):
                    ok, msg = app.test_key(body["api_key"])
                    if ok:
                        app.save_settings({"api_key": body["api_key"]})
                else:
                    ok, msg = app.test_key("")
                return self._json({"ok": ok, "message": msg, "state": app.state()})
            if path == "/api/run":
                if body:
                    app.save_settings(body)
                ok, msg = app.start()
                return self._json({"ok": ok, "message": msg})
            if path == "/api/stop":
                app.stop.set()
                return self._json({"ok": True})
            self._json({"error": "not found"}, 404)

    return H


def main():
    ap = argparse.ArgumentParser(description="Niche Finder app")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", default=str(ROOT / "reports" / "niches"))
    ap.add_argument("--demo", action="store_true", help="made-up sample data, no API key needed")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    out = Path(tempfile.mkdtemp(prefix="niche_demo_")) if a.demo else Path(a.out)
    app = App(out, a.demo)
    srv = None
    for port in range(a.port, a.port + 20):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
            break
        except OSError:
            continue
    if not srv:
        sys.exit("No free port found.")
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Niche Finder is running at {url}" + ("  (DEMO DATA)" if a.demo else ""))
    print("Keep this window open while you use it. Press Ctrl+C to quit.")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
