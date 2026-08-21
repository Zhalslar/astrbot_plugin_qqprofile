"""QQ 资料管理的 LLM 工具集。

基于 AstrBot 的 FunctionTool 机制（参考：
https://docs.astrbot.app/dev/star/guides/ai.html#%E5%AE%9A%E4%B9%89-tool），
把插件的头像、昵称、签名、在线状态、人格能力暴露为可被大语言模型
通过自然语言（工具调用 / function calling）直接使用的工具。
"""

from pathlib import Path
from typing import Any

import astrbot.api.message_components as Comp
from astrbot import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult, ToolSet
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from pydantic import Field
from pydantic.dataclasses import dataclass

from .status import status_mapping
from .utils import download_image

AgentContextWrapper = ContextWrapper[AstrAgentContext]

# 只有管理员（AstrBot 配置中的 admins_id）才可以修改 QQ 资料
_PERMISSION_DENIED = "错误：你没有权限执行此操作，只有机器人管理员才能修改QQ资料。"


def _params(properties: dict, required: list[str] | None = None) -> dict:
    """构造 JSON Schema 形式的 parameters。"""
    d = {"type": "object", "properties": properties}
    if required:
        d["required"] = required
    return d


def _is_admin(event: AstrMessageEvent) -> bool:
    return bool(getattr(event, "role", None) == "admin")


def _get_bot(event: AstrMessageEvent):
    """取 aiocqhttp 平台的 bot 实例（OneBot 协议端）。"""
    return getattr(event, "bot", None)


async def get_persona_id(ctx, event: AstrMessageEvent) -> str | None:
    """获取当前会话绑定的人格 ID（与 main.py 中逻辑一致）。"""
    umo = event.unified_msg_origin
    cid = await ctx.conversation_manager.get_curr_conversation_id(umo)
    if not cid:
        return None
    conversation = await ctx.conversation_manager.get_conversation(
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

    if persona_v3 := getattr(ctx.persona_manager, "selected_default_persona_v3", None):
        persona_id = persona_v3.get("name")
        if persona_id and persona_id != "[%None]":
            return persona_id
    return None


async def extract_image_url(event: AstrMessageEvent) -> str | None:
    """从消息链（含引用消息）中提取图片，返回 URL 或本地文件路径。"""
    for seg in event.get_messages():
        if isinstance(seg, Comp.Image):
            return await seg.get_file(allow_return_url=True) or None
        if isinstance(seg, Comp.Reply):
            for reply_seg in getattr(seg, "chain", None) or []:
                if isinstance(reply_seg, Comp.Image):
                    return await reply_seg.get_file(allow_return_url=True) or None
    return None


async def switch_persona(
    ctx,
    event: AstrMessageEvent,
    persona_id: str,
    sync_name: bool,
    avatar_dir: str,
) -> str:
    """切换当前会话人格，并在配置开启时同步昵称与存档头像。"""
    personas = ctx.provider_manager.personas
    if persona_id not in {p.get("name") for p in personas}:
        return f"人格【{persona_id}】不存在，请先用 qq_list_personas 工具查看可用人格。"
    await ctx.conversation_manager.update_conversation_persona_id(
        event.unified_msg_origin, persona_id
    )
    result = f"已切换人格【{persona_id}】"
    if not sync_name:
        return result
    bot = _get_bot(event)
    if not bot:
        return result + "（当前平台不支持同步昵称/头像）"
    try:
        await bot.set_qq_profile(nickname=persona_id)
        result += "，昵称已同步"
    except Exception as e:
        logger.error(f"切换人格时同步昵称失败：{e}")
        result += "（昵称同步失败）"
    avatar_path = Path(avatar_dir) / f"{persona_id}.jpg"
    if avatar_path.exists():
        try:
            await bot.set_qq_avatar(file=str(avatar_path))
            result += "，头像已同步"
        except Exception as e:
            logger.error(f"切换人格时同步头像失败：{e}")
            result += "（头像同步失败）"
    return result


@dataclass
class QQListPersonasTool(FunctionTool[AstrAgentContext]):
    """列出所有可用人格，供 LLM 确认人格名称。"""

    name: str = "qq_list_personas"
    description: str = (
        "列出 AstrBot 中当前可用的所有人格(persona)名称与简介，"
        "在用户要求切换人格时，应先调用此工具确认人格名称。"
    )
    parameters: dict = Field(default_factory=lambda: _params({}))

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        ctx = context.context.context
        personas = ctx.provider_manager.personas
        if not personas:
            return "当前没有配置任何人格。"
        lines = []
        for p in personas:
            prompt = (p.get("prompt") or "").strip()
            brief = prompt[:60] + ("…" if len(prompt) > 60 else "")
            lines.append(f"【{p.get('name')}】：{brief}")
        return "可用人格：\n" + "\n".join(lines)


@dataclass
class QQGetProfileTool(FunctionTool[AstrAgentContext]):
    """查询机器人当前的 QQ 资料。"""

    name: str = "qq_get_profile"
    description: str = (
        "查询机器人当前的QQ资料信息（昵称、QQ号），以及当前会话绑定的人格。"
        "当用户询问“你叫什么/你的昵称/你的QQ号”时使用。"
    )
    parameters: dict = Field(default_factory=lambda: _params({}))

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        ctx = context.context.context
        event = context.context.event
        bot = _get_bot(event)
        if not bot:
            return "当前会话的平台不支持查询QQ资料。"
        nickname = "未知"
        qq = "未知"
        try:
            info = await bot.get_login_info()
            nickname = info.get("nickname") or nickname
            qq = str(info.get("user_id") or qq)
        except Exception as e:
            return f"查询QQ资料失败：{e}"
        persona_id = await get_persona_id(ctx, event)
        parts = [f"当前昵称：{nickname}", f"QQ号：{qq}", f"当前会话人格：{persona_id or '无'}"]
        return "\n".join(parts)


@dataclass
class QQSetNicknameTool(FunctionTool[AstrAgentContext]):
    """修改机器人 QQ 昵称（仅管理员）。"""

    name: str = "qq_set_nickname"
    description: str = "修改机器人(QQ Bot)的昵称。用户说“把昵称改成xx”时使用。仅管理员可用。"
    parameters: dict = Field(
        default_factory=lambda: _params(
            {"nickname": {"type": "string", "description": "新的昵称，非空字符串"}},
            required=["nickname"],
        )
    )

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        nickname = (kwargs.get("nickname") or "").strip()
        if not nickname:
            return "请提供新的昵称（nickname 参数不能为空）。"
        event = context.context.event
        if not _is_admin(event):
            return _PERMISSION_DENIED
        bot = _get_bot(event)
        if not bot:
            return "当前会话的平台不支持设置QQ昵称。"
        try:
            await bot.set_qq_profile(nickname=nickname)
        except Exception as e:
            return f"设置昵称失败：{e}"
        return f"已将QQ昵称改为【{nickname}】"


@dataclass
class QQSetSignatureTool(FunctionTool[AstrAgentContext]):
    """修改机器人个性签名（仅管理员）。"""

    name: str = "qq_set_signature"
    description: str = (
        "修改机器人(QQ Bot)的个性签名（空间签名）。用户说“把签名改成xx/个性签名换成xx”时使用。"
        "仅管理员可用。"
    )
    parameters: dict = Field(
        default_factory=lambda: _params(
            {"signature": {"type": "string", "description": "新的个性签名内容"}},
            required=["signature"],
        )
    )

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        signature = (kwargs.get("signature") or "").strip()
        if not signature:
            return "请提供新的签名内容（signature 参数不能为空）。"
        event = context.context.event
        if not _is_admin(event):
            return _PERMISSION_DENIED
        bot = _get_bot(event)
        if not bot:
            return "当前会话的平台不支持设置QQ签名。"
        try:
            await bot.set_self_longnick(longNick=signature)
        except Exception as e:
            return f"设置签名失败：{e}"
        return f"个性签名已更新为：{signature}"


@dataclass
class QQSetStatusTool(FunctionTool[AstrAgentContext]):
    """设置机器人在线状态（仅管理员）。"""

    name: str = "qq_set_status"
    description: str = (
        "设置机器人(QQ Bot)的在线状态，如“我的电量”“听歌中”“摸鱼中”“隐身”等。"
        "用户用自然语言描述状态时，请从枚举中选择最接近的一项。仅管理员可用。"
    )
    parameters: dict = Field(
        default_factory=lambda: _params(
            {
                "state": {
                    "type": "string",
                    "description": "目标在线状态名称",
                    "enum": list(status_mapping.keys()),
                }
            },
            required=["state"],
        )
    )

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        state = (kwargs.get("state") or "").strip()
        event = context.context.event
        if not _is_admin(event):
            return _PERMISSION_DENIED
        bot = _get_bot(event)
        if not bot:
            return "当前会话的平台不支持设置在线状态。"
        params = status_mapping.get(state)
        if not params:
            # 模糊匹配兜底：允许用户口语描述
            for name, p in status_mapping.items():
                if state in name or name in state:
                    params = p
                    state = name
                    break
        if not params:
            supported = "、".join(status_mapping.keys())
            return f"状态【{state}】暂未支持。支持的状态有：{supported}"
        try:
            await bot.set_online_status(
                status=params[0], ext_status=params[1], battery_status=0
            )
        except Exception as e:
            return f"设置状态失败：{e}"
        return f"在线状态已设置为【{state}】"


@dataclass
class QQSetAvatarTool(FunctionTool[AstrAgentContext]):
    """设置机器人 QQ 头像（仅管理员）。"""

    name: str = "qq_set_avatar"
    description: str = (
        "修改机器人(QQ Bot)的QQ头像。用户随消息发送/引用了一张图片并要求“换头像/设成头像”时使用"
        "（此时无需 image_url，工具会自动取用户刚发的图片）；也可以显式传入 image_url。"
        "仅管理员可用。"
    )
    parameters: dict = Field(
        default_factory=lambda: _params(
            {
                "image_url": {
                    "type": "string",
                    "description": "用作头像的图片 URL（可选；未提供时自动取用户消息中附带或引用的图片）",
                }
            }
        )
    )
    avatar_dir: str = ""

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        event = context.context.event
        if not _is_admin(event):
            return _PERMISSION_DENIED
        bot = _get_bot(event)
        if not bot:
            return "当前会话的平台不支持设置QQ头像。"
        image_url = (kwargs.get("image_url") or "").strip()
        if not image_url:
            try:
                image_url = await extract_image_url(event)
            except Exception as e:
                return f"提取图片失败：{e}"
        if not image_url:
            return (
                "没有找到图片：请让用户直接发送/引用一张图片后再要求换头像，"
                "或显式提供 image_url 参数。"
            )
        try:
            await bot.set_qq_avatar(file=image_url)
        except Exception as e:
            return f"设置头像失败：{e}"
        result = "头像已换好啦~"
        ctx = context.context.context
        persona_id = await get_persona_id(ctx, event)
        if persona_id and self.avatar_dir and image_url.startswith(("http://", "https://")):
            save_path = Path(self.avatar_dir) / f"{persona_id}.jpg"
            try:
                await download_image(image_url, str(save_path))
                result += f"（已存档，切换回人格【{persona_id}】时会自动恢复）"
            except Exception as e:
                logger.error(f"保存头像失败：{e}")
        return result


@dataclass
class QQSwitchPersonaTool(FunctionTool[AstrAgentContext]):
    """切换当前会话人格（仅管理员），可同步昵称与头像。"""

    name: str = "qq_switch_persona"
    description: str = (
        "将当前会话切换为指定人格(persona)。在切换人格前应先使用 qq_list_personas "
        "查看可用人格名称。若配置了同步开关，还会同步机器人的QQ昵称与已存档头像。仅管理员可用。"
    )
    parameters: dict = Field(
        default_factory=lambda: _params(
            {"persona_id": {"type": "string", "description": "目标人格名称，须与人格列表中的名称一致"}},
            required=["persona_id"],
        )
    )
    sync_name: bool = False
    avatar_dir: str = ""

    async def call(self, context: AgentContextWrapper, **kwargs: Any) -> ToolExecResult:
        persona_id = (kwargs.get("persona_id") or "").strip()
        if not persona_id:
            return "请提供目标人格名称（persona_id 参数不能为空）。"
        event = context.context.event
        if not _is_admin(event):
            return _PERMISSION_DENIED
        ctx = context.context.context
        return await switch_persona(
            ctx, event, persona_id, self.sync_name, self.avatar_dir
        )


def build_qq_profile_tools(
    sync_name: bool = False, avatar_dir: str = ""
) -> list[FunctionTool[AstrAgentContext]]:
    """构建全部 QQ 资料管理工具。"""
    return [
        QQListPersonasTool(),
        QQGetProfileTool(),
        QQSetNicknameTool(),
        QQSetSignatureTool(),
        QQSetStatusTool(),
        QQSetAvatarTool(avatar_dir=avatar_dir),
        QQSwitchPersonaTool(sync_name=sync_name, avatar_dir=avatar_dir),
    ]


def build_qq_profile_toolset(
    sync_name: bool = False, avatar_dir: str = ""
) -> ToolSet:
    """构建包含全部 QQ 资料管理工具的 ToolSet。"""
    return ToolSet(build_qq_profile_tools(sync_name=sync_name, avatar_dir=avatar_dir))