"""日志：输出到 QQBotData/logs/framework.log（无控制台时也在其中可查）。"""
import logging
import os

from framework.paths import LOGS_DIR


def setup_logger(level: str = "INFO") -> logging.Logger:
    os.makedirs(LOGS_DIR, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

        file_handler = logging.FileHandler(
            os.path.join(LOGS_DIR, "framework.log"), encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    return logging.getLogger("framework")
