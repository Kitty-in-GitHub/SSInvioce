"""Temporary LAN receiver so a phone can scan a QR code and upload screenshots.

Runs a tiny FastAPI app on a separate port (bound to 0.0.0.0) with a one-off
token. The main API stays on 127.0.0.1; closing the dialog stops this server.
"""

from __future__ import annotations

import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import segno
import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from ..logging_config import get_logger

log = get_logger("mobile")

SESSION_TTL_SECONDS = 15 * 60
DEFAULT_PORT = 8766
MAX_PORT_TRIES = 20


def lan_ip() -> str:
    """Best-effort local network address (no packets are sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _free_port(start: int = DEFAULT_PORT) -> int:
    for port in range(start, start + MAX_PORT_TRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError("没有可用端口（8766 起 20 个都被占用）")


def _expired(session: dict) -> bool:
    return datetime.now(timezone.utc).isoformat() > session["expires_at"]


MOBILE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>传到电脑 · 报销助手</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f4f6fa; color: #1f2937; }
  main { max-width: 480px; margin: 0 auto; padding: 24px 18px 40px; }
  h1 { font-size: 1.3rem; margin: 0 0 6px; }
  .hint { margin: 0 0 18px; color: #5c6678; font-size: .9rem; line-height: 1.5; }
  .pick { display: block; border: 2px dashed #c4cfdf; border-radius: 14px; padding: 22px 16px;
          text-align: center; background: #fff; color: #163a7a; font-weight: 600; }
  .pick:active { background: #eef3fb; }
  #list { display: grid; gap: 8px; margin: 14px 0; }
  .item { display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid #e2e7f0;
          border-radius: 10px; padding: 8px 10px; font-size: .86rem; }
  .item img { width: 44px; height: 44px; object-fit: cover; border-radius: 6px; }
  .item span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  button { width: 100%; padding: 14px; border: 0; border-radius: 12px; background: #163a7a; color: #fff;
           font-size: 1rem; font-weight: 600; }
  button:disabled { opacity: .45; }
  #status { margin: 14px 0 0; font-size: .86rem; color: #5c6678; min-height: 1.4em; }
  .foot { margin-top: 26px; font-size: .78rem; color: #8a94a6; line-height: 1.6; }
</style>
</head>
<body>
<main>
  <h1>传到电脑</h1>
  <p class="hint">选手机截图或拍照，上传后会直接出现在电脑的「收件箱」。</p>
  <label class="pick">选择图片 / 拍照
    <input id="file" type="file" accept="image/*,.pdf" multiple hidden>
  </label>
  <div id="list"></div>
  <button id="upload" disabled>上传</button>
  <p id="status"></p>
  <p class="foot">同一 Wi-Fi 下才能访问。关闭电脑上的扫码窗口后本页立即失效。</p>
</main>
<script>
(function () {
  var token = "__TOKEN__";
  var input = document.getElementById("file");
  var list = document.getElementById("list");
  var btn = document.getElementById("upload");
  var status = document.getElementById("status");
  var files = [];

  function render() {
    list.innerHTML = "";
    files.forEach(function (f) {
      var row = document.createElement("div");
      row.className = "item";
      if (f.type && f.type.indexOf("image/") === 0) {
        var img = document.createElement("img");
        img.src = URL.createObjectURL(f);
        row.appendChild(img);
      }
      var name = document.createElement("span");
      name.textContent = f.name || "截图";
      row.appendChild(name);
      list.appendChild(row);
    });
    btn.disabled = files.length === 0;
  }

  input.addEventListener("change", function () {
    files = Array.prototype.slice.call(input.files || []);
    status.textContent = "";
    render();
  });

  btn.addEventListener("click", function () {
    if (!files.length) return;
    var fd = new FormData();
    files.forEach(function (f) { fd.append("files", f); });
    btn.disabled = true;
    status.textContent = "上传中…";
    fetch("/m/" + token + "/upload", { method: "POST", body: fd })
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (r) {
        if (!r.ok) throw new Error((r.data && r.data.detail) || "上传失败");
        var failed = (r.data.failed || []).length;
        status.textContent = "已上传 " + r.data.count + " 个" + (failed ? "，失败 " + failed + " 个" : "") + "，可以继续选择";
        files = [];
        input.value = "";
        render();
      })
      .catch(function (err) {
        status.textContent = err.message || "上传失败";
        btn.disabled = false;
      });
  });
})();
</script>
</body>
</html>
"""


def build_app(session: dict) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan="off")

    def check(token: str) -> None:
        if token != session["token"]:
            raise HTTPException(status_code=404, detail="not found")
        if _expired(session):
            raise HTTPException(status_code=410, detail="链接已过期")

    @app.get("/m/{token}", response_class=HTMLResponse)
    def page(token: str):
        check(token)
        return HTMLResponse(MOBILE_HTML.replace("__TOKEN__", token))

    @app.post("/m/{token}/upload")
    async def upload(token: str, files: list[UploadFile] = File(...)):
        check(token)
        from ..routers.materials import upload_materials_fast

        result = await upload_materials_fast(files=files)
        now = datetime.now(timezone.utc).isoformat()
        for item in result.get("uploaded", []):
            session["received"].append({"name": item.original_name, "at": now})
        session["uploads"] = int(session.get("uploads", 0)) + int(result.get("count", 0))
        return {
            "ok": True,
            "count": result.get("count", 0),
            "failed": result.get("failed", []),
            "received": len(session["received"]),
        }

    return app


class MobileReceiver:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._session: dict | None = None

    def start(self) -> dict:
        with self._lock:
            self._stop_locked()
            token = uuid.uuid4().hex
            port = _free_port()
            created = datetime.now(timezone.utc)
            expires = created + timedelta(seconds=SESSION_TTL_SECONDS)
            ip = lan_ip()
            session = {
                "token": token,
                "port": port,
                "created_at": created.isoformat(),
                "expires_at": expires.isoformat(),
                "received": [],
                "uploads": 0,
                "url": f"http://{ip}:{port}/m/{token}",
            }
            app = build_app(session)
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=port,
                log_level="warning",
                access_log=False,
                lifespan="off",
            )
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, name="mobile-receiver", daemon=True)
            thread.start()
            deadline = time.time() + 6
            while not server.started and time.time() < deadline:
                time.sleep(0.05)
            if not server.started:
                server.should_exit = True
                raise RuntimeError("扫码接收服务启动失败（端口或防火墙问题）")
            session["qr"] = segno.make(session["url"], error="m").png_data_uri(scale=6, border=2)
            self._session = session
            self._server = server
            self._thread = thread
            log.info("mobile receiver started port=%s ip=%s", port, ip)
            return self._payload_locked(session)

    def status(self) -> dict:
        with self._lock:
            if not self._session:
                return {"active": False}
            if _expired(self._session):
                self._stop_locked()
                return {"active": False, "expired": True}
            return self._payload_locked(self._session)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def _payload_locked(self, session: dict) -> dict:
        expires = datetime.fromisoformat(session["expires_at"])
        remain = max(0, int((expires - datetime.now(timezone.utc)).total_seconds()))
        return {
            "active": True,
            "url": session["url"],
            "qr": session.get("qr", ""),
            "port": session["port"],
            "expires_at": session["expires_at"],
            "expires_in": remain,
            "received": len(session["received"]),
            "items": list(session["received"][-8:]),
        }

    def _stop_locked(self) -> None:
        server, thread, session = self._server, self._thread, self._session
        self._server = None
        self._thread = None
        self._session = None
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=3)
        if session is not None:
            log.info("mobile receiver stopped port=%s received=%s", session.get("port"), len(session["received"]))


receiver = MobileReceiver()
