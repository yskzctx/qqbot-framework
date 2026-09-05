"""便携化路径：EXE 同目录创建 QQBotData/{config.json, logs/, modules/}"""
import os
import sys


def app_root() -> str:
    """EXE 所在目录（打包后）或源码根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # framework/ 的上级


DATA_DIR = os.path.join(app_root(), "QQBotData")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
MODULES_DIR = os.path.join(DATA_DIR, "modules")
DATA_STORE_DIR = os.path.join(DATA_DIR, "data")   # 模块产生的数据（config.json 每模块一份）


def ensure_dirs():
    for d in (DATA_DIR, LOGS_DIR, MODULES_DIR, DATA_STORE_DIR):
        os.makedirs(d, exist_ok=True)
