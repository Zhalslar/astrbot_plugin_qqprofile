import os
import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse
import aiofiles
import aiohttp
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent


async def get_nickname(event: AiocqhttpMessageEvent) -> str | None:
    info = await event.bot.get_stranger_info(user_id=int(event.get_self_id()))
    return info.get("nickname") or info.get("nick")


async def download_image(url: str, save_path: str) -> None:
    """下载或从本地复制图片并保存到指定路径"""
    # 兼容 URL 编码及 file:// 协议或本地文件绝对路径
    unquoted = unquote(url)

    # 提取本地路径
    local_path = None
    if unquoted.startswith("file:///"):
        # file:///C:/path 或 file:///path
        parsed = urlparse(unquoted)
        local_path = parsed.path
        if os.name == "nt" and local_path.startswith("/") and len(local_path) > 2 and local_path[2] == ":":
            local_path = local_path.lstrip("/")
    elif unquoted.startswith("file://"):
        local_path = unquoted[7:]
    else:
        # 判断是否为 Windows 绝对路径 (如 C:\... 或 C:/...) 或 Unix 绝对路径 (/...)
        if (len(unquoted) > 2 and unquoted[1] == ":" and (unquoted[2] == "\\" or unquoted[2] == "/")) or unquoted.startswith("/"):
            local_path = unquoted

    if local_path and os.path.exists(local_path):
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        shutil.copyfile(local_path, save_path)
        return

    # 网络 URL 下载
    url = url.replace("https://", "http://")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                async with aiofiles.open(save_path, "wb") as f:
                    await f.write(await resp.read())
            else:
                raise Exception(f"图片下载失败，状态码: {resp.status}")
