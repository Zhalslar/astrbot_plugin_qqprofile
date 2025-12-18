import astrbot.api.message_components as Comp
from astrbot import logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform import AstrMessageEvent
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.core.star.filter.permission import PermissionType
from astrbot.core.star.star_tools import StarTools

from .status import status_mapping
from .utils import download_image, get_nickname


class QQProfilePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.curr_nickname = None
        self.avatar_dir = StarTools.get_data_dir("astrbot_plugin_qqprofile") / "avatar"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)

    async def get_curr_persona_id(self, event: AstrMessageEvent) -> str | None:
        """获取当前会话的人格ID"""
        umo = event.unified_msg_origin
        cid = await self.context.conversation_manager.get_curr_conversation_id(umo)
        if not cid:
            return
        conversation = await self.context.conversation_manager.get_conversation(
            unified_msg_origin=umo,
            conversation_id=cid,
            create_if_not_exists=True,
        )
        if (
            conversation
            and conversation.persona_id
            and conversation.persona_id != "[%None]"
        ):
            return conversation.persona_id

        # 兜底
        if persona_v3 := self.context.persona_manager.selected_default_persona_v3:
            persona_id = persona_v3.get("name")

            if persona_id and persona_id != "[%None]":
                return persona_id

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置头像")
    async def set_avatar(self, event: AiocqhttpMessageEvent):
        "将引用的图片设置为头像"
        chain = event.get_messages()
        img_url = None
        for seg in chain:
            if isinstance(seg, Comp.Image):
                img_url = seg.url
                break
            elif isinstance(seg, Comp.Reply):
                if seg.chain:
                    for reply_seg in seg.chain:
                        if isinstance(reply_seg, Comp.Image):
                            img_url = reply_seg.url
                            break
        if not img_url:
            yield event.plain_result("需要引用一张图片")
            return

        await event.bot.set_qq_avatar(file=img_url)
        yield event.plain_result("我换头像啦~")
        if persona_id := await self.get_curr_persona_id(event):
            save_path = self.avatar_dir / f"{persona_id}.jpg"
            try:
                await download_image(img_url, str(save_path))
                logger.debug(f"头像已保存到：{str(save_path)}")
            except Exception as e:
                logger.error(f"保存头像失败：{e}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置签名")
    async def set_longnick(
        self, event: AiocqhttpMessageEvent, longnick: str | None = None
    ):
        """设置Bot的签名，并同步空间（可在QQ里关掉）"""
        if not longnick:
            yield event.plain_result("没提供新签名呢")
            return
        await event.bot.set_self_longnick(longNick=longnick)
        yield event.plain_result(f"我签名已更新：{longnick}")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置状态")
    async def set_status(
        self, event: AiocqhttpMessageEvent, status_name: str | None = None
    ):
        """设置Bot的在线状态"""
        if not status_name:
            yield event.plain_result("没提供新状态呢")
            return
        params = status_mapping.get(status_name, None)
        if not params:
            yield event.plain_result(f"状态【{status_name}】暂未支持")
            return
        await event.bot.set_online_status(
            status=params[0], ext_status=params[1], battery_status=0
        )
        yield event.plain_result(f"我状态已更新为【{status_name}】")

    @filter.permission_type(PermissionType.ADMIN)
    @filter.command("设置昵称")
    async def set_nickname(
        self, event: AiocqhttpMessageEvent, nickname: str | None = None
    ):
        """设置Bot的昵称"""
        nickname = nickname or await self.get_curr_persona_id(event)
        if not nickname:
            yield event.plain_result("未输入新昵称")
            return
        await event.bot.set_qq_profile(nickname=nickname)
        yield event.plain_result(f"我昵称已改为【{nickname}】")

    async def sync_nickname_and_avatar(
        self, event: AiocqhttpMessageEvent, persona_id: str
    ):
        """在请求 LLM 前同步bot昵称与人格名"""

        if not self.curr_nickname:
            if new_nickname := await get_nickname(event):
                self.curr_nickname = new_nickname

        if self.curr_nickname != persona_id:
            self.curr_nickname = persona_id

            await event.bot.set_qq_profile(nickname=persona_id)
            logger.debug(f"已同步bot的昵称为：{persona_id}")
            avatar_path = self.avatar_dir / f"{persona_id}.jpg"
            if avatar_path.exists():
                await event.bot.set_qq_avatar(file=str(avatar_path))
                logger.debug(f"已同步bot的头像为：{str(avatar_path)}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("切换人格")
    async def change_persona(
        self, event: AiocqhttpMessageEvent, persona_id: str | None = None
    ):
        # 确定目标人格ID
        if persona_id:
            target_persona = next(
                (
                    p
                    for p in self.context.provider_manager.personas
                    if p["name"] == persona_id
                ),
                None,
            )
            if not target_persona:
                yield event.plain_result(f"【{persona_id}】人格不存在")
                return
            target_persona_id = target_persona["name"]
        else:
            target_persona_id = await self.get_curr_persona_id(event)
            if not target_persona_id:
                return

        # 切换人格
        await self.context.conversation_manager.update_conversation_persona_id(
            event.unified_msg_origin, target_persona_id
        )
        yield event.plain_result(f"已切换人格【{target_persona_id}】")

        # 同步昵称和头像（如果配置允许）
        if self.conf["sync_name"]:
            await self.sync_nickname_and_avatar(event, target_persona_id)

        event.stop_event()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("人格列表", alias={"查看人格列表"})
    async def list_persona(
        self, event: AiocqhttpMessageEvent, persona_id: str | None = None
    ):
        """查看人格列表"""
        msg = ""
        for persona in self.context.provider_manager.personas:
            msg += f"\n\n【{persona['name']}】:\n{persona['prompt']}"
        yield event.plain_result(msg.strip())
        return
