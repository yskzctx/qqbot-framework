"""配置加载与保存。首次运行自动在 QQBotData/ 下生成 config.json 模板。"""
import json
import os

from framework.paths import CONFIG_PATH

DEFAULT_CONFIG = {
    # 面板 + OneBot API 共用一个端口
    "server": {
        "host": "0.0.0.0",
        "port": 2280,
    },
    "web": {
        # 面板密码（哈希后存储）。留空 = 首次打开面板时引导设置密码
        "password": "",
        # 启动后自动打开浏览器进入面板
        "auto_open_browser": True,
    },
    "onebot": {
        # QQ 端（如 NapCat）连入时必须携带此 token，留空则不校验
        "access_token": "在这里填你的API密钥",
        # 反向 WS：框架主动连出去的 OneBot 服务端地址（可选，留空不启用）
        "reverse_ws_url": "",
    },
    # AI 配置（OpenAI 兼容格式），模块可通过 app.ai.chat() 调用
    "ai": {
        "api_base": "",   # 如 https://api.openai.com 或自建中转
        "api_key": "",
        "model": "",
    },
    # 权限：管理员 QQ 号列表（所有模块共享，系统级操作需要管理员身份）
    "permissions": {
        "admins": ["在这里填你的QQ号"],
    },
    "qq": {
        "process_names": ["QQ.exe"],
        "poll_interval": 5,
    },
    "inject": {
        # 是否在检测到 QQ 进程后自动注入 DLL
        "enabled": False,
        # 要注入的 DLL（相对 EXE 目录或绝对路径），由你提供，放入 modules/ 即可
        "dll_path": "QQBotData/modules/hook.dll",
    },
    "log_level": "INFO",
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: str, data: dict):
        self.path = path
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


def load_config(path: str = CONFIG_PATH) -> Config:
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    # utf-8-sig 兼容带 BOM 的文件（记事本/PowerShell 5.1 写入的配置）
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    # 补齐缺失键，保证旧配置兼容新版本
    return Config(path, _deep_merge(DEFAULT_CONFIG, data))
