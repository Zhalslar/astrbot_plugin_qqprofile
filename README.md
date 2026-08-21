<div align="center">

![:name](https://count.getloli.com/@astrbot_plugin_QQProfile?name=astrbot_plugin_QQProfile&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_qqprofile

_✨ QQ资料配置插件 ✨_  

[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0.html)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.0%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-Zhalslar-blue)](https://github.com/Zhalslar)

</div>

## 🤝 介绍

本插件利用Onebot协议接口配置QQ机器人的头像、昵称、签名、状态。

**v1.2.0 新增：LLM 自然语言工具调用**（基于 [AstrBot AI 开发文档](https://docs.astrbot.app/dev/star/guides/ai.html)）
- 将全部 QQ 资料操作注册为 AstrBot 的 LLM 工具（`FunctionTool`），
  你可以直接用大白话让机器人改自己的资料，无需记忆指令；
- 同时提供「资料」指令，显式进入资料管理助手（由 LLM 自主选择工具执行）。

## 📦 安装

在astrbot的插件市场搜索astrbot_plugin_qqprofile，点击安装即可  

## ⚙️ 配置

请在astrbot面板配置，插件管理 -> astrbot_plugin_qqprofile -> 操作 -> 插件配置

| 配置项 | 说明 | 默认 |
|:---:|:---:|:---:|
| `sync_name` | 切换人格时使bot的QQ昵称与人格名同步 | false |
| `llm_tools` | 是否注册LLM工具（自然语言修改QQ资料），关闭后仅保留指令方式 | true |

## 🐔 使用说明

### 指令表

|     指令     |             说明              |
|:----------:|:---------------------------:|
| [引用图片]设置头像 |        将引用的这张图片设置为头像        |
|  设置昵称 XXX  |        将Bot的昵称改为XXX         |
|  设置签名 XXX  | 将Bot的签名改为XXX，并同步空间（可在QQ里关掉） |
|  设置状态 XXX  |     设置Bot的在线状态（如“我的电量”）     |
|  切换人格 XXX  |     设置bot人格为XXX，同时切换该人格对应的昵称和头像    |
|  人格列表  |     查看所有人格的详细信息     |
|  资料 XXX  |  自然语言管理QQ资料（见下方示例）  |

### 🌟 自然语言用法（LLM 工具）

开启 `llm_tools` 配置后，两处入口均可使用自然语言：

1. **正常聊天时直接说**（需要当前人格启用了工具调用，LLM 会自动选择本插件注册的工具）：
   - 「把你的昵称改成 小可爱」
   - 「签名换成 摸鱼中」
   - 「在线状态改成 我的电量」
   - 「把头像换成这张图」（随消息发一张图片）
   - 「切换到 猫娘 人格」
   - 「你现在叫什么名字？」

2. **使用「资料」指令显式进入资料管理助手**（推荐，无需依赖人格工具配置）：
   - 「资料 把昵称改成 小可爱」
   - 「资料 签名换成 摸鱼中」
   - 「资料 头像换成这张图」（随消息发一张图片）
   - 「资料 切换人格到 猫娘」
   - 「资料 我现在的昵称是什么？」

> 权限说明：查询类操作（查资料、列人格）全员可用；
> 修改类操作（改昵称/签名/状态/头像、切人格）仅管理员（`admins_id`）可用，
> 非管理员请求时工具会拒绝并告知。

### 示例图

![eb62d8cb2e51b1caadab31f746ab923](https://github.com/user-attachments/assets/5dff2926-83c1-4aa8-8b2a-da3bf3baef36)

## 👥 贡献指南

- 🌟 Star 这个项目！（点右上角的星星，感谢支持！）
- 🐛 提交 Issue 报告问题
- 💡 提出新功能建议
- 🔧 提交 Pull Request 改进代码

## 📌 注意事项

- 本插件目前仅测试了napcat协议端，其他协议端可能会存在一些不兼容问题（以具体情况为准）
- 「资料」指令与 LLM 工具注册需要 AstrBot ≥ v4.5.7（`tool_loop_agent` / `add_llm_tools` API，
  详见 [AstrBot AI 开发文档](https://docs.astrbot.app/dev/star/guides/ai.html)）；旧版本仍可使用原有指令
- LLM 工具需要当前会话使用的模型支持函数调用(function calling / tools use)；
  若不支持，「资料」指令会提示执行失败
- 想第一时间得到反馈的可以来作者的插件反馈群（QQ群）：460973561