"""BotAPI：模块用的 QQ 操作便捷封装（OneBot 11 动作）。

bot.app 即核心 App 对象（可用于 app.get_module_config / app.ai.chat 等）。
"""


class BotAPI:
    def __init__(self, app):
        self.app = app
        self.onebot = app.onebot

    async def call_action(self, action: str, params: dict | None = None, **kw) -> dict:
        return await self.onebot.call_action(action, params, **kw)

    async def send_private_msg(self, user_id: int, message) -> dict:
        return await self.call_action("send_private_msg",
                                      {"user_id": user_id, "message": message})

    async def send_group_msg(self, group_id: int, message) -> dict:
        return await self.call_action("send_group_msg",
                                      {"group_id": group_id, "message": message})

    async def get_login_info(self) -> dict:
        return await self.call_action("get_login_info")

    async def get_stranger_info(self, user_id: int) -> dict:
        return await self.call_action("get_stranger_info", {"user_id": user_id})

    def is_admin(self, user_id) -> bool:
        return self.app.is_admin(user_id)

    def get_module_config(self, name: str) -> dict:
        return self.app.get_module_config(name)

    def set_module_config(self, name: str, cfg: dict):
        self.app.set_module_config(name, cfg)

    async def delete_msg(self, message_id: int) -> dict:
        return await self.call_action("delete_msg", {"message_id": message_id})
