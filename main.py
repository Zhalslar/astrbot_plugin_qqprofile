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
from .tools import build_qq_profile_tools, build_qq_profile_toolset
from .utils import download_image, get_nickname

# 「资料」自然语言指令的触发词，用于剥离指令前缀
PROFILE_CMDS = ("资料管理", "QQ资料", "管理资料", "资料")


class QQProfilePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.conf = config
        self.curr_nickname = None
        self.avatar_dir = StarTools.get_data_dir("astrbot_plugin_qqprofile") / "avatar"
        self.avatar_dir.mkdir(parents=True, exist_ok=True)
        if self.conf.get("llm_tools", True):
            self._register_llm_tools()

    def _register_llm_tools(self) -> None:
        """将 QQ 资料管理能力注册为 LLM 工具，支持自然语言调用。

        参考：https://docs.astrbot.app/dev/star/guides/ai.html#%E6%B3%A8%E5%86%8C-tool-%E5%88%B0-astrbot
        """
        tools = build_qq_profile_tools(
            sync_name=bool(self.conf.get("sync_name", False)),
            avatar_dir=str(self.avatar_dir),
        )
        try:
            # >= v4.5.1 推荐用法
            self.context.add_llm_tools(*tools)
        except AttributeError:
            # < v4.5.1 旧版兼容
            tool_mgr = self.context.provider_manager.llm_tools
            for tool in tools:
                tool_mgr.func_list.append(tool)
        logger.info(f"QQProfile: 已注册 {len(tools)} 个 LLM 工具（自然语言管理QQ资料）")

    @staticmethod
    def _strip_profile_command(text: str) -> str:
        """剥离「资料」等指令前缀，返回剩余的自然语言描述。"""
        text = text.strip()
        for cmd in PROFILE_CMDS:
            if text == cmd:
                return ""
            if text.startswith(cmd) and (
                len(text) == len(cmd) or text[len(cmd)] in (" ", "\u3000", "\n", "\t")
            ):
                return text[len(cmd) :].strip()
        return text

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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("资料", alias={"QQ资料", "资料管理", "管理资料"})
    async def manage_profile(self, event: AiocqhttpMessageEvent):
        """用自然语言管理QQ资料。

        例如：
        - 「资料 把昵称改成 小可爱」
        - 「资料 签名换成 摸鱼中」
        - 「资料 在线状态变成 我的电量」
        - 「资料 看看我现在叫什么」
        - 「资料 切换人格到 猫娘」（附带图片时还可：『资料 把头像换成这张图』）

        实现方式：调用 AstrBot 的 tool_loop_agent，让 LLM 自主选择
        tools.py 中注册的 QQ 资料工具执行（参考官方 AI 开发文档）。
        """
        prompt = self._strip_profile_command(event.get_message_str())
        if not prompt:
            yield event.plain_result(
                "可以这样对我说：\n"
                "「资料 把昵称改成 小可爱」\n"
                "「资料 签名换成 摸鱼中」\n"
                "「资料 在线状态设为 我的电量」\n"
                "「资料 头像换成这张图」（随消息发送一张图片）\n"
                "「资料 切换人格到 猫娘」\n"
                "「资料 我现在的昵称是什么？」"
            )
            return

        try:
            prov_id = await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
        except Exception as e:
            yield event.plain_result(f"获取当前AI模型失败：{e}")
            return

        toolset = build_qq_profile_toolset(
            sync_name=bool(self.conf.get("sync_name", False)),
            avatar_dir=str(self.avatar_dir),
        )
        system_prompt = (
            "你是「QQ资料管理助手」。根据用户的自然语言请求，选择最合适的工具"
            "查询或修改机器人的QQ资料（头像、昵称、个性签名、在线状态、人格）。\n"
            "要求：\n"
            "1. 切换人格前先用 qq_list_personas 确认人格名称；\n"
            "2. 工具调用失败时如实转述错误信息，并给出补救建议；\n"
            "3. 操作类工具仅管理员可用，工具返回权限不足时请礼貌告知用户；\n"
            "4. 全程使用简体中文，回答简洁、口语化。"
        )
        try:
            llm_resp = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=prov_id,
                prompt=prompt,
                tools=toolset,
                system_prompt=system_prompt,
                max_steps=8,
                tool_call_timeout=60,
            )
            text = (llm_resp.completion_text or "").strip()
            yield event.plain_result(text or "已处理完成。")
        except Exception as e:
            logger.error(f"自然语言管理资料失败：{e}")
            yield event.plain_result(
                f"执行失败：{e}\n"
                "建议检查：当前会话使用的模型是否支持函数调用(工具调用)。"
            )
