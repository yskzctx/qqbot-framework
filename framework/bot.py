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

    # ---------- 联系人与分组 ----------

    def get_contacts(self) -> dict:
        """好友与群列表缓存（需 NapCat 已连接；面板可刷新）。"""
        return self.app.get_contacts()

    def refresh_contacts(self):
        """触发重新拉取好友/群列表（后台执行）。"""
        self.app.request_contacts_refresh()

    def get_groups_by_tag(self, tag: str) -> list:
        """获取打上某标签的所有群（完整群信息列表）。"""
        return self.app.get_groups_by_tag(tag)

    def get_friends_by_tag(self, tag: str) -> list:
        """获取打上某标签的所有好友。"""
        return self.app.get_friends_by_tag(tag)

    # ---------- 消息数据库 ----------

    def db_query(self, limit=100, offset=0, msg_type=None, chat_id=None,
                 keyword=None) -> dict:
        """查询消息历史。返回 {"total": 总数, "rows": [{time, chat_id, user_id,
        nickname, raw_message, message_id}...]}（按时间倒序）。"""
        return self.app.msgdb.query(limit=limit, offset=offset, msg_type=msg_type,
                                    chat_id=str(chat_id) if chat_id else None,
                                    keyword=keyword)

    def db_stats(self) -> dict:
        """消息库统计：总数/大小/每天条数。"""
        return self.app.msgdb.stats()

    def db_add(self, event: dict):
        """手动写入一条消息记录（一般不用，框架自动入库）。"""
        self.app.msgdb.add(event)

    def get_module_config(self, name: str) -> dict:
        return self.app.get_module_config(name)

    def set_module_config(self, name: str, cfg: dict):
        self.app.set_module_config(name, cfg)

    async def delete_msg(self, message_id: int) -> dict:
        return await self.call_action("delete_msg", {"message_id": message_id})
