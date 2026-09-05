"""BotAPI：插件用的 QQ 操作便捷封装（OneBot 11 动作）。"""


class BotAPI:
    def __init__(self, onebot):
        self.onebot = onebot

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

    async def delete_msg(self, message_id: int) -> dict:
        return await self.call_action("delete_msg", {"message_id": message_id})
