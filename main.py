"""QQ 机器人核心（EXE / 启动器）。

便携运行：EXE 同目录自动生成 QQBotData/ 配置文件夹
  QQBotData/
  ├── config.json      配置（填 API 密钥、面板密码）
  ├── logs/            运行日志
  └── modules/         模块文件夹（随时往里加 .py 模块，面板可重载）

启动后无窗口、托盘常驻，并自动打开浏览器进入管理面板。
"""
import asyncio
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from framework import paths
from framework.config import load_config
from framework.logger import setup_logger
from framework.app import App


def _fatal(msg: str):
    """无控制台模式下用弹窗报告致命错误。"""
    paths.ensure_dirs()
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "QQ 机器人核心 - 启动失败", 0x10)
    except Exception:
        pass
    sys.exit(1)


def main():
    paths.ensure_dirs()
    config = load_config(paths.CONFIG_PATH)
    log = setup_logger(config.get("log_level", "INFO"))

    app = App(config)
    tray = None

    try:
        if "--no-tray" not in sys.argv:
            from framework.tray import Tray
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tray = Tray(app, loop)
            tray.start()
            loop.run_until_complete(app.run())
            loop.close()
        else:
            asyncio.run(app.run())
    except OSError as e:
        # 最常见：端口被占用（重复启动）
        log.exception("启动失败")
        _fatal(f"启动失败: {e}\n\n"
               f"可能原因：框架已在运行（检查托盘/任务管理器），\n"
               f"或端口被其他程序占用。可在 {paths.CONFIG_PATH} 中修改端口。")
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C，退出")
    finally:
        if tray:
            tray.stop()


if __name__ == "__main__":
    main()
