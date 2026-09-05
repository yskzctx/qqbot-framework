"""模块开发 API 装饰器（万物皆可插件）。

模块内使用：
    from framework.plugins import cmd, api, event

    @cmd("签到")                        # 聊天命令，收到"签到"触发，args=剩余参数列表
    async def sign(bot, event, args): ...

    @cmd("删库", admin=True)            # 仅管理员可触发的命令
    async def danger(bot, event, args): ...

    @event(priority=10)                 # 事件订阅，priority 越小越先；
    async def watch(bot, event): ...    # 返回 False 可拦截事件（后续订阅者不再收到）

    @event(post_type="message")         # 只订阅指定 post_type
    async def on_msg(bot, event): ...

    @api("GET", "/stats")               # 模块自有 HTTP API: /api/m/<模块文件名>/stats
    async def stats(bot, request): ...  # 返回 aiohttp Response / json 字符串 / dict

不使用装饰器也行：传统 on_event / register / on_config / on_unload 约定照旧。
"""


def cmd(name: str, *, admin: bool = False):
    """注册聊天命令：消息为 name（或 name + 空格 + 参数）时触发。"""
    def deco(fn):
        fn._qqbot_cmd = (name, bool(admin))
        return fn
    return deco


def event(post_type: str | None = None, priority: int = 100):
    """订阅事件；priority 越小越先执行；处理函数返回 False 拦截后续。"""
    def deco(fn):
        fn._qqbot_event = (post_type, priority)
        return fn
    return deco


def api(method: str, path: str):
    """注册模块自有 HTTP API（挂载在 /api/m/<模块文件名><path>）。"""
    def deco(fn):
        fn._qqbot_api = (method.upper(), path)
        return fn
    return deco
