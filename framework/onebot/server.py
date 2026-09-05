"""OneBot 11 协议服务端。

框架作为 OneBot 服务端运行，QQ 侧实现（如 NapCat，它负责在原版 QQ 进程内
收发消息）通过正向 WS 连入，或框架通过 reverse_ws_url 反向连出。

- 事件流向：QQ -> 框架 -> 插件 / Web 面板
- 动作流向：插件 / Web 面板 -> 框架 -> QQ（echo 关联请求与响应）
- 鉴权：access_token，支持 Authorization: Bearer <token> 或 ?access_token=
"""
import asyncio
import json
import logging
import time
import uuid

import aiohttp
from aiohttp import WSMsgType, web

log = logging.getLogger("onebot.server")


class OneBotServer:
    def __init__(self, app):
        self.app = app
        self.clients: set = set()          # 已连接的 QQ 侧 OneBot 客户端（WS）
        self.pending: dict[str, asyncio.Future] = {}
        self._reverse_task: asyncio.Task | None = None
        self._closing = False

    # ---------- 生命周期 ----------

    def register_routes(self, router):
        """把 OneBot 端点注册到共享 HTTP 服务（与面板同一端口）。"""
        router.add_get("/onebot/v11/ws", self.handle_ws)
        router.add_post("/onebot/v11/events", self.handle_http_event)
        router.add_post("/onebot/v11/{action}", self.handle_http_action)

    async def start(self):
        cfg = self.app.config["onebot"]
        if cfg.get("reverse_ws_url"):
            self._reverse_task = asyncio.create_task(self._reverse_loop(cfg["reverse_ws_url"]))
        log.info("OneBot 端点已就绪 ws://<host>:%d/onebot/v11/ws（与面板同端口）",
                 self.app.config["server"]["port"])

    async def stop(self):
        self._closing = True
        if self._reverse_task:
            self._reverse_task.cancel()
        for fut in self.pending.values():
            if not fut.done():
                fut.cancel()
        self.pending.clear()
        for ws in list(self.clients):
            await ws.close()
        self.clients.clear()
        log.info("OneBot 端点已停止")

    # ---------- 鉴权 ----------

    def _check_token(self, request) -> bool:
        token = self.app.config["onebot"].get("access_token", "")
        if not token:
            return True
        auth = request.headers.get("Authorization", "")
        if auth in (f"Bearer {token}", f"Token {token}"):
            return True
        return request.query.get("access_token") == token

    # ---------- 正向 WS：QQ 侧连入 ----------

    async def handle_ws(self, request):
        if not self._check_token(request):
            return web.Response(status=401, text="invalid access_token")
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        self.clients.add(ws)
        log.info("OneBot 客户端已连接（当前在线 %d）", len(self.clients))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._on_packet(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    log.warning("OneBot WS 错误: %s", ws.exception())
                    break
        finally:
            self.clients.discard(ws)
            log.info("OneBot 客户端已断开（当前在线 %d）", len(self.clients))
        return ws

    # ---------- 反向 WS：框架连出 ----------

    async def _reverse_loop(self, url: str):
        token = self.app.config["onebot"].get("access_token", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        while not self._closing:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, headers=headers, heartbeat=30) as ws:
                        log.info("反向 WS 已连接: %s", url)
                        self.clients.add(ws)
                        try:
                            async for msg in ws:
                                if msg.type == WSMsgType.TEXT:
                                    await self._on_packet(msg.data)
                                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                                    break
                        finally:
                            self.clients.discard(ws)
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.warning("反向 WS 连接失败: %s，5 秒后重试", e)
            await asyncio.sleep(5)

    # ---------- 包处理 ----------

    async def _on_packet(self, raw: str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            log.warning("收到无法解析的数据包: %.200s", raw)
            return

        if "post_type" in data:                     # 上报事件
            data.setdefault("_received_at", time.time())
            self.app.push_event(data)
            self.app.plugins.dispatch(data)
        elif "echo" in data and "retcode" in data:  # 动作响应
            fut = self.pending.pop(str(data["echo"]), None)
            if fut and not fut.done():
                fut.set_result(data)
        else:
            log.debug("未知数据包: %.200s", raw)

    # ---------- 动作调用（框架 -> QQ） ----------

    async def call_action(self, action: str, params: dict | None = None,
                          timeout: float = 30) -> dict:
        if not self.clients:
            raise RuntimeError("没有已连接的 OneBot 客户端（QQ 侧未接入）")
        echo = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pending[echo] = fut
        payload = json.dumps({"action": action, "params": params or {}, "echo": echo},
                             ensure_ascii=False)
        ws = next(iter(self.clients))
        await ws.send_str(payload)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(echo, None)

    # ---------- HTTP 事件上报（兼容 NapCat HTTP POST 模式） ----------

    async def handle_http_event(self, request):
        if not self._check_token(request):
            return web.json_response({"status": "failed", "retcode": 1403}, status=401)
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "failed", "retcode": 1400}, status=400)
        data.setdefault("post_type", "unknown")
        data.setdefault("_received_at", time.time())
        self.app.push_event(data)
        self.app.plugins.dispatch(data)
        return web.json_response({"status": "ok", "retcode": 0})

    # ---------- HTTP 动作入口（外部工具 -> 框架 -> QQ） ----------

    async def handle_http_action(self, request):
        if not self._check_token(request):
            return web.json_response({"status": "failed", "retcode": 1403}, status=401)
        action = request.match_info["action"]
        params = {}
        if request.can_read_body:
            try:
                params = await request.json()
            except Exception:
                return web.json_response({"status": "failed", "retcode": 1400}, status=400)
        try:
            result = await self.call_action(action, params)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"status": "failed", "retcode": 1200, "message": str(e)})
