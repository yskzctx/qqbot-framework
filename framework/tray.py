"""系统托盘：框架启动后缩到托盘，无主窗口。"""
import logging
import threading

from framework.paths import MODULES_DIR

log = logging.getLogger("tray")


def _make_icon():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=15, fill=(34, 168, 107, 255))
    try:
        font = ImageFont.load_default(size=34)
        d.text((32, 32), "Q", fill=(255, 255, 255, 255), font=font, anchor="mm")
    except TypeError:  # 旧版 Pillow 不支持 size 参数
        d.ellipse([22, 14, 42, 34], outline=(255, 255, 255, 255), width=4)
        d.rectangle([36, 30, 50, 44], fill=(34, 168, 107, 255))
        d.ellipse([36, 30, 48, 42], outline=(255, 255, 255, 255), width=3)
    return img


class Tray:
    def __init__(self, app, loop):
        import pystray
        self.app = app
        self.loop = loop
        menu = pystray.Menu(
            pystray.MenuItem("打开管理面板", self._open_panel, default=True),
            pystray.MenuItem("打开模块文件夹", self._open_modules),
            pystray.MenuItem("QQ 状态", self._show_status, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出框架", self._exit),
        )
        self.icon = pystray.Icon("QQBotFramework", _make_icon(),
                                 "QQ 机器人框架", menu)

    def _open_panel(self, *_):
        import webbrowser
        port = self.app.config["server"]["port"]
        webbrowser.open(f"http://127.0.0.1:{port}/")

    def _open_modules(self, *_):
        import subprocess
        subprocess.Popen(["explorer", MODULES_DIR])

    def _show_status(self, *_):
        qq = self.app.qq_info
        state = f"PID {qq['pid']}" if qq else "未检测到"
        self.icon.notify(f"QQ 进程: {state} · OneBot 连接: {len(self.app.onebot.clients)} 个",
                         "QQ 机器人框架")

    def _exit(self, *_):
        log.info("托盘触发退出")
        self.loop.call_soon_threadsafe(self.app.request_shutdown)

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True, name="tray").start()
        log.info("托盘图标已启动")

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass
