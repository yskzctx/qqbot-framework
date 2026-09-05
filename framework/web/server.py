"""Web 面板服务端（与 OneBot API 共用 0.0.0.0:2280）。

认证流程：
- GET  /api/auth_state   {"need_setup": true/false}
- POST /api/setup        首次设置密码 {"password": "..."}（仅未设置时可用）
- POST /api/login        {"password": "..."} -> {"token": 会话token}
- 之后所有 /api/* 请求带 X-Access-Token: <会话token>（仅存页面内存，刷新即失效）

模块相关：
- GET  /api/modules                      已装模块列表（自动扫描）
- GET  /api/modules/{name}/ui            模块自带配置界面 HTML
- GET  /api/modules/{name}/config        读取模块数据（QQBotData/data/<name>.json）
- POST /api/modules/{name}/config        保存模块数据（不回写模块文件）

AI 配置：
- GET  /api/ai/config / POST /api/ai/config / POST /api/ai/test
"""
import asyncio
import json
import logging
import os
import time

from aiohttp import WSMsgType, web

import framework
from framework import auth
from framework.paths import DATA_STORE_DIR, MODULES_DIR

log = logging.getLogger("web")

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "index.html")


class WebServer:
    def __init__(self, app):
        self.app = app
        self.subscribers: set = set()      # 面板 WS 连接
        self.sessions: set[str] = set()    # 会话 token（内存，重启即失效）
        self._runner: web.AppRunner | None = None
        self._push_task: asyncio.Task | None = None

    # ---------- 生命周期 ----------

    async def start(self):
        cfg = self.app.config["server"]
        web_app = web.Application()
        web_app.router.add_get("/", self.handle_index)
        # 认证
        web_app.router.add_get("/api/auth_state", self.handle_auth_state)
        web_app.router.add_post("/api/setup", self.handle_setup)
        web_app.router.add_post("/api/login", self.handle_login)
        # 面板
        web_app.router.add_get("/api/status", self.handle_status)
        web_app.router.add_get("/api/events", self.handle_events)
        web_app.router.add_get("/api/ws", self.handle_ws)
        web_app.router.add_post("/api/action", self.handle_action)
        web_app.router.add_post("/api/reload_modules", self.handle_reload_modules)
        web_app.router.add_post("/api/shutdown", self.handle_shutdown)
        # 模块
        web_app.router.add_get("/api/modules", self.handle_modules)
        web_app.router.add_get("/api/modules/{name}/ui", self.handle_module_ui)
        web_app.router.add_get("/api/modules/{name}/config", self.handle_module_config_get)
        web_app.router.add_post("/api/modules/{name}/config", self.handle_module_config_set)
        # AI
        web_app.router.add_get("/api/ai/config", self.handle_ai_config_get)
        web_app.router.add_post("/api/ai/config", self.handle_ai_config_set)
        web_app.router.add_post("/api/ai/test", self.handle_ai_test)

        # OneBot 端点共用同一端口
        self.app.onebot.register_routes(web_app.router)

        self._runner = web.AppRunner(web_app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, cfg.get("host", "0.0.0.0"), cfg.get("port", 2280))
        await site.start()
        await self.app.onebot.start()
        log.info("服务已启动 http://%s:%d/（面板与 OneBot API 同端口）",
                 cfg.get("host"), cfg.get("port"))
        self._push_task = asyncio.create_task(self._push_loop())

    async def stop(self):
        if self._push_task:
            self._push_task.cancel()
        for ws in list(self.subscribers):
            await ws.close()
        self.subscribers.clear()
        if self._runner:
            await self._runner.cleanup()
        log.info("Web 服务已停止")

    # ---------- 认证 ----------

    def _password_hash(self) -> str:
        return self.app.config["web"].get("password", "")

    def _need_setup(self) -> bool:
        return not self._password_hash()

    def _authorized(self, request) -> bool:
        token = request.headers.get("X-Access-Token", "") or request.query.get("token", "")
        return bool(token) and token in self.sessions

    async def handle_auth_state(self, request):
        return web.json_response({"need_setup": self._need_setup()})

    async def handle_setup(self, request):
        if not self._need_setup():
            return web.json_response({"ok": False, "error": "密码已设置，请直接登录"}, status=403)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad request"}, status=400)
        pwd = str(body.get("password", "")).strip()
        if len(pwd) < 4:
            return web.json_response({"ok": False, "error": "密码至少 4 位"}, status=400)
        self.app.config["web"]["password"] = auth.hash_password(pwd)
        self.app.config.save()
        log.info("面板密码已设置")
        return web.json_response({"ok": True})

    async def handle_login(self, request):
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad request"}, status=400)
        if self._need_setup():
            return web.json_response({"ok": False, "error": "尚未设置密码"}, status=403)
        if auth.verify_password(str(body.get("password", "")), self._password_hash()):
            token = auth.new_session_token()
            self.sessions.add(token)
            return web.json_response({"ok": True, "token": token})
        return web.json_response({"ok": False, "error": "密码错误"}, status=401)

    async def handle_index(self, request):
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html", charset="utf-8")

    # ---------- 面板 API ----------

    def _status_snapshot(self) -> dict:
        qq = self.app.qq_info
        return {
            "version": framework.__version__,
            "uptime_s": int(time.time() - self.app.start_time),
            "qq": qq,
            "bot_count": len(self.app.onebot.clients),
            "modules": self.app.plugins.list_modules(),
            "modules_dir": MODULES_DIR,
            "server_port": self.app.config["server"]["port"],
            "mcp_enabled": self.app.mcp.running,
            "mcp_token": self.app.config["mcp"].get("token", "") if self.app.mcp.running else "",
        }

    async def handle_status(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(self._status_snapshot())

    async def handle_events(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(list(self.app.recent_events))

    async def handle_action(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "bad request"}, status=400)
        try:
            result = await self.app.onebot.call_action(
                body.get("action", ""), body.get("params") or {})
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=502)

    async def handle_reload_modules(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        loaded = await asyncio.get_running_loop().run_in_executor(
            None, self.app.plugins.reload_all)
        return web.json_response({"ok": True, "modules": loaded})

    async def handle_shutdown(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        log.info("收到 Web 面板关闭指令")
        asyncio.get_running_loop().call_later(0.5, self.app.request_shutdown)
        return web.json_response({"ok": True, "message": "框架即将关闭"})

    # ---------- 模块 API ----------

    async def handle_modules(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(self.app.plugins.list_modules())

    async def handle_module_ui(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        name = request.match_info["name"]
        meta = {m["file"]: m for m in self.app.plugins.list_modules()}
        if name not in meta:
            return web.Response(status=404, text="模块不存在")
        if not meta[name]["has_ui"]:
            return web.Response(status=404, text="该模块未提供界面")
        path = os.path.join(MODULES_DIR, name + ".html")
        with open(path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html", charset="utf-8")

    async def handle_module_config_get(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        name = request.match_info["name"]
        return web.json_response(self.app.get_module_config(name))

    async def handle_module_config_set(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        name = request.match_info["name"]
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad request"}, status=400)
        self.app.set_module_config(name, body.get("config", {}))
        return web.json_response({"ok": True})

    # ---------- AI API ----------

    async def handle_ai_config_get(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        cfg = self.app.config["ai"]
        return web.json_response({"api_base": cfg.get("api_base", ""),
                                  "api_key": cfg.get("api_key", ""),
                                  "model": cfg.get("model", ""),
                                  "ready": self.app.ai.ready()})

    async def handle_ai_config_set(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad request"}, status=400)
        cfg = self.app.config["ai"]
        cfg["api_base"] = str(body.get("api_base", "")).strip()
        cfg["api_key"] = str(body.get("api_key", "")).strip()
        cfg["model"] = str(body.get("model", "")).strip()
        self.app.config.save()
        log.info("AI 配置已保存（model=%s）", cfg["model"])
        return web.json_response({"ok": True, "ready": self.app.ai.ready()})

    async def handle_ai_test(self, request):
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            reply = await self.app.ai.chat([{"role": "user", "content": "你好，请回复：测试成功"}])
            return web.json_response({"ok": True, "reply": reply})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=502)

    # ---------- 实时推送 ----------

    async def handle_ws(self, request):
        if not self._authorized(request):
            return web.Response(status=401, text="unauthorized")
        ws = web.WebSocketResponse(heartbeat=25)
        await ws.prepare(request)
        self.subscribers.add(ws)
        try:
            await ws.send_str(json.dumps({"type": "status",
                                          "data": self._status_snapshot()},
                                         ensure_ascii=False))
            await ws.send_str(json.dumps({"type": "events",
                                          "data": list(self.app.recent_events)},
                                         ensure_ascii=False))
            async for msg in ws:
                if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        finally:
            self.subscribers.discard(ws)
        return ws

    async def _push_loop(self):
        while True:
            await asyncio.sleep(5)
            if not self.subscribers:
                continue
            payload = json.dumps({"type": "status", "data": self._status_snapshot()},
                                 ensure_ascii=False)
            for ws in list(self.subscribers):
                try:
                    await ws.send_str(payload)
                except Exception:
                    self.subscribers.discard(ws)
