# JMBot-Pro

QQ 机器人插件：在群聊 / 私聊发送本子 ID，机器人自动从禁漫（JM Comic）下载漫画、生成 PDF 并发送文件，支持 PDF 加密、批量下载、JM 账号登录、下载产物自动清理。

提供两种部署方式（二选一即可）：

| 方式 | 目录 | 适合人群 |
|---|---|---|
| [方法一：ncatbot 版（JMBot_v5）](#方法一ncatbot-版jmbot_v5) | [`JMBot_v5/`](JMBot_v5/) | 想要一个独立轻量的 QQ 机器人 |
| [方法二：AstrBot 插件](#方法二astrbot-插件astrbot_plugin_jmbot) | [`astrbot_plugin_jmbot/`](astrbot_plugin_jmbot/) | 已经在用 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 框架 |

> **⚠️ 免责声明**：本项目仅供编程学习与技术研究，内容涉及成人向漫画站点，**未满 18 岁请勿使用**。请于下载后 24 小时内自行删除相关内容，勿用于商业用途，请支持正版。使用本项目产生的任何后果由使用者自行承担。

---

## 致谢与项目来源（Acknowledgements）

本项目的开发**特别感谢以下项目**：

- **[Estecsky/JMBot](https://github.com/Estecsky/JMBot)** —— **本项目由它改编而来**，插件的核心思路（`/jm <id>` 下载 → 生成 PDF → 自动发送）源自该项目，并在此基础上新增了批量下载、JM 账号登录、PDF 加密、下载路径可配置、产物自动清理等大量功能。没有它就没有 JMBot-Pro。
- **[hect0x7/JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)**（MIT License）—— 禁漫下载的核心能力（API、域名解析、图片混淆还原、登录）全部由该库提供，本项目只是它的使用者。
- [Sora-o-tobu/JM-NcatBot](https://github.com/Sora-o-tobu/JM-NcatBot) —— Estecsky/JMBot 的上游来源，一并致谢。
- [NapCatQQ](https://napcat.napneko.icu/) / [NcatBot](https://docs.ncatbot.xyz/) / [AstrBot](https://github.com/AstrBotDevs/AstrBot) —— QQ 协议端与机器人框架。

## 功能特性

- `/jm <id>` 下载本子并生成 PDF 发送（群聊 / 私聊）
- **批量下载**：`/jm 350234 350235 350236`，或一条消息里写多条 `/jm` 指令；`/jm350234`（无空格）、`/jm 350234极品`（数字后带备注）均可识别
- **JM 账号登录**：聊天指令保存账号密码（本机存储），自动登录，可查看仅登录用户可见的内容
- **PDF 加密**：群聊发送的 PDF 可自动加密码（私聊不加密）
- **下载路径可配置**：聊天指令或配置文件修改，旧文件自动迁移
- **自动清理**：下载产物保留 3 天，过期自动删除（每 6 小时清理一次）
- “本子不存在”等错误的友好提示
- 启动时后台自动登录 JM，不阻塞消息处理

---

## 方法一：ncatbot 版（JMBot_v5）

独立运行的 QQ 机器人，架构：**NapCat（QQ 协议端）←WebSocket→ ncatbot（Python 框架）←插件→ JMBot**。

### 1. 环境准备

- Windows 10/11（其他平台自行调整 NapCat 启动方式）
- Python 3.10+（开发时使用 3.13）
- [NapCat.Shell](https://napcat.napneko.icu/guide/boot-shell)（免安装版 QQ 协议端，需本机已安装 QQNT）

### 2. 安装依赖

```powershell
cd JMBot_v5
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> PowerShell 提示“禁止运行脚本”时，先执行一次：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 3. 配置

```powershell
Copy-Item config.example.yaml config.yaml
```

编辑 `config.yaml`，把 `bot_uin`（机器人 QQ）、`root`（超管 QQ）改成你自己的。

然后在 NapCat 里配置 WebSocket 服务端：打开 `NapCat.Shell\webui.html` 进入 WebUI（默认 `localhost:6099`）→ 网络配置 → 添加 **WebSocket 服务器**，端口填 `3001`，token 留空（与 `config.yaml` 的 `ws_token: ""` 保持一致）。

### 4. 启动

**方式 A：一键启动脚本**（推荐）

编辑 `start_all.bat` 顶部的变量（`NAPCAT_DIR`、`BOT_QQ` 等），然后双击运行。脚本会：启动 NapCat → 等待 3001 端口就绪 → 启动机器人。

**方式 B：手动启动**

```powershell
# 终端 1：启动 NapCat（带 QQ 号参数可快速登录）
cd C:\NapCat.Shell
.\launcher-user.bat 你的QQ号

# 终端 2：启动机器人
cd JMBot_v5
.\.venv\Scripts\ncatbot.exe run
```

首次登录会弹二维码，用手机 QQ 扫一下；之后带 QQ 号参数启动即可快速登录。

### 5. 使用

| 命令 | 说明 | 权限 |
|---|---|---|
| `/jm <id> [id ...]` | 下载并发送 PDF，支持批量 | 群聊需先开启，私聊可用 |
| `开启JMBot` / `关闭JMBot` | 开关群聊下载 | 超管 |
| `测试JMBot` | 测试插件是否存活 | 超管 |
| `打开加密` / `关闭加密` | 群聊 PDF 是否加密 | 超管 |
| `PDF密码` / `设置PDF密码 xxx` | 查看 / 设置加密密码 | 超管 |
| `设置JM账号 xxx` / `设置JM密码 xxx` | 保存 JM 账号并自动登录 | 超管 |
| `JM登录` / `JM状态` / `清除JM账号` | 登录 / 查看状态 / 清除 | 超管 |
| `JM帮助` | 查看命令列表 | 超管 |

> 提示：设置类命令请**一条消息发一条**。群聊命令直接发送，私聊命令发给机器人。

---

## 方法二：AstrBot 插件（astrbot_plugin_jmbot）

已在使用 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 框架的话，把本插件装进去即可，功能与方法一完全一致。

### 安装

1. 下载本仓库，把 `astrbot_plugin_jmbot` 文件夹压缩成 zip（**zip 根目录必须是单一的 `astrbot_plugin_jmbot/` 文件夹**，不能把文件散在 zip 根层）
2. AstrBot WebUI → 插件管理 → 从文件上传安装（依赖会自动安装）
3. 插件管理 → JMBot → 配置，填写**超管QQ号**，按需调整群聊开关 / 加密 / 下载路径

详细说明见 [`astrbot_plugin_jmbot/README.md`](astrbot_plugin_jmbot/README.md)。

### 使用

私聊机器人（或群聊）发送：

```
/jm 350234
设置JM账号 你的用户名
设置JM密码 你的密码
JM状态
```

管理命令（`开启JMBot`、`设置PDF密码`、`设置下载路径` 等）仅超管可用。

---

## 目录结构

```
JMBot-Pro
├── JMBot_v5/                  # 方法一：ncatbot 版
│   ├── config.example.yaml    #   主配置模板（复制为 config.yaml）
│   ├── start_all.bat          #   一键启动脚本（NapCat + 机器人）
│   ├── test_jm_login.py       #   JM 登录链路自测脚本
│   ├── requirements.txt
│   └── plugins/JMBot/         #   机器人插件本体
└── astrbot_plugin_jmbot/      # 方法二：AstrBot 插件
    ├── main.py                #   插件本体
    ├── _conf_schema.json      #   WebUI 配置项定义
    └── ...
```

## 常见问题

- **下载报“域名解析失败”**：JM 域名时常被墙/更换。jmcomic 会自动获取可用域名；也可以参考 JMBot_v5 插件目录里的 jmcomic 配置（`plugins/JMBot/config/config.yml`）手动指定 `client.domain`。
- **登录返回 401**：检查账号密码；注意每条设置命令单独发送，避免参数被换行污染。
- **群聊没有反应**：群聊默认关闭，先私聊机器人发 `开启JMBot`。
- **修改了插件代码不生效**：ncatbot 版给机器人发 `!reload JMBot`；AstrBot 版在 WebUI 点重载插件。

## 开发说明

**本项目（JMBot-Pro）的全部代码由 [Trae](https://www.trae.ai/)（AI 编程助手）开发完成**——由使用者提出需求、反馈测试结果，Trae 负责分析、编码与修复，经多轮迭代达到当前形态。

## License

本项目代码以 [MIT License](LICENSE) 发布。依赖的上游项目 [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) 为 MIT License，[Estecsky/JMBot](https://github.com/Estecsky/JMBot) 未声明许可证，在此致谢。
