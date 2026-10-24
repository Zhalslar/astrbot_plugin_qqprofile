import asyncio
import shutil
from pathlib import Path
from urllib.parse import unquote

import aiofiles
import aiohttp

from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)


async def get_nickname(event: AiocqhttpMessageEvent) -> str | None:
    info = await event.bot.get_stranger_info(user_id=int(event.get_self_id()))
    return info.get("nickname") or info.get("nick")


async def download_image(url: str, save_path: str) -> None:
    """Download or copy an image to a local path.

    Args:
        url: Image URL or local file path.
        save_path: Destination file path.

    Raises:
        Exception: If a remote image cannot be downloaded.
    """
    source_path = Path(unquote(url))
    if source_path.is_file():
        await asyncio.to_thread(shutil.copyfile, source_path, save_path)
        return

    url = url.replace("https://", "http://")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(save_path, "wb") as f:
                    await f.write(await resp.read())
            else:
                raise Exception(f"图片下载失败，状态码: {resp.status}")
