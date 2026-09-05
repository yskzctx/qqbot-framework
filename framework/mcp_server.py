"""MCP 远程控制服务（供隧道穿透后通过 MCP 协议远程管理本机）。

- 端点: http://0.0.0.0:<mcp.port>/mcp （Streamable HTTP，无状态）
- 鉴权: Authorization: Bearer <mcp.token>（必须配置 token，隧道是公网可达的）
- 工具: 命令执行 / 截图 / 鼠标 / 键盘 / 文件读写

在支持 MCP 的客户端（如 ZCode）中这样接入：
    {
      "mcpServers": {
        "cloudpc": {
          "type": "http",
          "url": "http://<隧道地址>/mcp",
          "headers": {"Authorization": "Bearer <mcp.token>"}
        }
      }
    }
"""
import ctypes
import io
import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("mcp")

VK_MAP = {
    "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "home": 0x24, "end": 0x23,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "win": 0x5B, "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_MAP[_c] = ord(_c.upper())
for _d in "0123456789":
    VK_MAP[_d] = ord(_d)

_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _mouse_event(flags, dx=0, dy=0):
    _user32.SetCursorPos(int(dx), int(dy))
    time.sleep(0.02)
    _user32.mouse_event(flags, 0, 0, 0, 0)


def _send_key(vk: int, down: bool):
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_ubyte * 32)]
        _anonymous_ = ("i",)
        _fields_ = [("type", ctypes.c_ulong), ("i", _I)]

    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(vk, 0, 0 if down else 2, 0, None)
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def build_mcp(app):
    from mcp.server.fastmcp import FastMCP, Image

    mcp = FastMCP("cloudpc", stateless_http=True)

    @mcp.tool()
    def run_command(command: str, timeout: int = 60) -> str:
        """在云电脑上执行 PowerShell 命令，返回 stdout/stderr。"""
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                               capture_output=True, timeout=timeout)
            out = (r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace"))
            return out.strip()[:8000] or "(无输出)"
        except subprocess.TimeoutExpired:
            return f"命令超时（>{timeout}s）"

    @mcp.tool()
    def screenshot() -> Image:
        """截取云电脑全屏，返回图片。"""
        import PIL.ImageGrab
        img = PIL.ImageGrab.grab(all_screens=True)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Image(data=buf.getvalue(), format="png")

    @mcp.tool()
    def left_click(x: int, y: int) -> str:
        """移动鼠标到 (x, y) 并左键单击。屏幕坐标（像素）。"""
        _mouse_event(0x0002 | 0x0004, x, y)
        return f"已在 ({x},{y}) 左键单击"

    @mcp.tool()
    def right_click(x: int, y: int) -> str:
        """移动鼠标到 (x, y) 并右键单击。"""
        _mouse_event(0x0008 | 0x0010, x, y)
        return f"已在 ({x},{y}) 右键单击"

    @mcp.tool()
    def double_click(x: int, y: int) -> str:
        """移动鼠标到 (x, y) 并左键双击。"""
        _mouse_event(0x0002 | 0x0004, x, y)
        time.sleep(0.05)
        _mouse_event(0x0002 | 0x0004, x, y)
        return f"已在 ({x},{y}) 双击"

    @mcp.tool()
    def type_text(text: str) -> str:
        """向当前焦点窗口输入文本（Unicode 逐字符输入，支持中文）。"""
        for ch in text:
            if ch == "\n":
                _send_key(VK_MAP["enter"], True); _send_key(VK_MAP["enter"], False)
                continue
            class KBINPUT(ctypes.Structure):
                _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                            ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]
            class INP(ctypes.Structure):
                class _U(ctypes.Union):
                    _fields_ = [("ki", KBINPUT), ("padding", ctypes.c_ubyte * 32)]
                _anonymous_ = ("u",)
                _fields_ = [("type", ctypes.c_ulong), ("u", _U)]
            down = INP(type=1); down.ki = KBINPUT(0, ord(ch), 4, 0, None)
            up = INP(type=1); up.ki = KBINPUT(0, ord(ch), 4 | 2, 0, None)
            _user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INP))
            _user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INP))
        return f"已输入 {len(text)} 个字符"

    @mcp.tool()
    def press_key(keys: str) -> str:
        """按下组合键，如 "enter"、"ctrl+c"、"win+d"、"alt+tab"。"""
        parts = [p.strip().lower() for p in keys.split("+") if p.strip()]
        vks = []
        for p in parts:
            if p not in VK_MAP:
                return f"不支持的按键: {p}（可用: {', '.join(sorted(VK_MAP))}）"
            vks.append(VK_MAP[p])
        for vk in vks:
            _send_key(vk, True)
        for vk in reversed(vks):
            _send_key(vk, False)
        return f"已按下 {keys}"

    @mcp.tool()
    def list_dir(path: str) -> str:
        """列出目录内容。"""
        entries = os.listdir(path)
        out = []
        for e in sorted(entries)[:200]:
            full = os.path.join(path, e)
            out.append(("[目录] " if os.path.isdir(full) else "[文件] ") + e)
        return "\n".join(out) or "(空目录)"

    @mcp.tool()
    def read_file(path: str, max_bytes: int = 60000) -> str:
        """读取文本文件内容（UTF-8，超长截断）。"""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)

    @mcp.tool()
    def write_file(path: str, content: str) -> str:
        """写入文本文件（UTF-8，覆盖）。"""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {path}（{len(content)} 字符）"

    return mcp


class _TokenMiddleware:
    """ASGI 中间件：校验 Bearer token。"""

    def __init__(self, asgi_app, token: str):
        self.app = asgi_app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}
            auth = headers.get(b"authorization", b"").decode("latin-1")
            if auth != f"Bearer {self.token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body",
                            "body": b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


class MCPServer:
    def __init__(self, app):
        self.app = app
        self.running = False

    def start(self):
        cfg = self.app.config["mcp"]
        if not cfg.get("enabled"):
            log.info("MCP 服务未启用")
            return
        token = cfg.get("token", "")
        if not token or "填" in token:
            # 首次运行自动生成随机 token，写回配置（面板概览页可见）
            import secrets
            token = secrets.token_hex(12)
            cfg["token"] = token
            self.app.config.save()
            log.info("已自动生成 MCP 访问 token 并写入 config.json: %s", token)
        port = int(cfg.get("port", 2281))
        threading.Thread(target=self._serve, args=(token, port),
                         daemon=True, name="mcp").start()

    def _serve(self, token: str, port: int):
        try:
            import uvicorn
            mcp = build_mcp(self.app)
            asgi = _TokenMiddleware(mcp.streamable_http_app(), token)
            server = uvicorn.Server(uvicorn.Config(
                asgi, host="0.0.0.0", port=port, log_level="warning"))
            self.running = True
            log.info("MCP 服务已启动 http://0.0.0.0:%d/mcp（Bearer token 鉴权）", port)
            server.run()
        except Exception:
            log.exception("MCP 服务启动失败")
        finally:
            self.running = False
