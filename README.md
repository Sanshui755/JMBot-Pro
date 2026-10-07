# JMBot-Pro

> [!CAUTION]
> **请勿大批量、高频率下载漫画**
>
> 本工具仅面向**个人自用、按需下载**的场景。大批量或高频率的连续下载会给禁漫站点服务器带来沉重负担，影响其他用户的正常访问，同时极易触发站点风控，导致你的 JM 账号被限流乃至封禁。
>
> 请自觉控制下载的数量与频率。因滥用造成的一切后果（包括但不限于账号封禁、IP 限制），由使用者自行承担。

<details>
<summary>🛠️ 开发说明（面向二次开发者，普通用户可忽略）</summary>

> **本项目主要由 AI（Trae）辅助完成开发与迭代**，仅在作者本人的 Windows 环境下做过有限测试，跨平台（尤其 Linux/macOS）与各类硬件配置可能存在未覆盖的问题。欢迎通过 Issue 反馈，也欢迎 PR。

#### 项目结构

本仓库为 AstrBot 插件形态，核心下载能力来自 [`jmcomic`](https://github.com/hect0x7/JMComic-Crawler-Python) 库：

| 目录                    | 框架         | 入口                                    |
| ----------------------- | ------------ | --------------------------------------- |
| `astrbot_plugin_jmbot/` | AstrBot 插件 | `main.py`，配置定义 `_conf_schema.json` |

> 另有不依赖 AstrBot 的 NcatBot 独立机器人部署形态，已拆分至姊妹仓库 **[Sanshui755/JMBot-NcatBot](https://github.com/Sanshui755/JMBot-NcatBot)**。

#### 本地开发

1. 建议在独立虚拟环境中安装依赖：`pip install -r astrbot_plugin_jmbot/requirements.txt`（另需一套 AstrBot 运行环境用于加载插件）。
2. 将插件目录软链 / 拷贝到 AstrBot 的 `data/plugins/astrbot_plugin_jmbot/`，在 WebUI 中「重载插件」即可热更新调试。
3. 插件运行期数据位于 `data/plugin_data/astrbot_plugin_jmbot/`：`jm_account.json`（凭据）、`realesrgan/`、`waifu2x/`（超分二进制，首次使用自动下载）。

#### 编码约定

- **消息隔离**：所有指令处理器 `priority=500000`（高于陪伴/记忆类插件），认领消息后在全部回复发送完毕调用 `event.stop_event()`，避免其他插件重复响应或把指令写入记忆。
- **命令兼容**：新增指令时同步处理三件事——`@filter.command` 注册、`on_jm_nospace` 无空格兜底（如 `/jms关键词`）、私聊管理入口的 `SKIP_JM_PATTERN` 跳过正则。
- **阻塞操作**：jmcomic 下载、subprocess 超分等同步调用一律包 `asyncio.to_thread`，并设置超时。
- **超分工具**：Real-ESRGAN 与 waifu2x 均为 ncnn-vulkan 外部二进制（无需 torch），统一登记在 `SUPERRES_TOOLS`，新增工具只需补一项配置。
- 提交前请通过 `python -m py_compile main.py` 与 JSON 校验。

#### 发版流程

更新版本号（`main.py` 的 `@register`、启动日志、`metadata.yaml` 三处）→ 提交推送 → 打同名 tag → 打包根目录为单一 `astrbot_plugin_jmbot/` 的 zip → 创建 GitHub Release 并上传 zip，Release notes 按版本列出变更。

</details>

基于 QQ 机器人框架的禁漫（JM Comic）下载插件：在群聊或私聊中发送漫画 ID，机器人即自动完成下载、生成 PDF 并回传文件。支持批量下载、JM 账号登录、PDF 加密、下载路径自定义与产物定期清理。

本项目以 **AstrBot 插件**形态交付（NapCat + AstrBot），自带 WebUI 可视化配置，Python 依赖自动安装，部署最简单。

> 另有不依赖 AstrBot 的 **NcatBot 独立机器人**部署形态（适合想运行一个独立、轻量机器人的用户），已拆分至姊妹仓库：**[Sanshui755/JMBot-NcatBot](https://github.com/Sanshui755/JMBot-NcatBot)**。

---

## ⚖️ 使用须知与免责声明

在使用本项目前，请务必阅读并同意以下条款：

1. **内容性质**：本项目涉及成人向（R18）内容站点，**禁止未满 18 周岁的用户安装或使用**。
2. **用途限制**：本项目仅用于编程技术、网络通信与自动化方向的学习与研究。使用者应确保其行为符合所在国家或地区的法律法规，以及目标站点的服务条款。
3. **合理使用**：请**勿大批量、高频率下载**漫画。大量并发请求会显著加重目标站点服务器负担，影响其正常运行，也可能导致账号或 IP 被站点风控限制。请按需、少量下载，自觉控制频率。
4. **版权提示**：通过本项目获取的任何漫画、图片及其衍生文件，其著作权均归原作者或相应权利人所有。请**支持正版**，并在获取后 **24 小时内删除**，不得用于传播、分享、二次上传或任何商业用途。
5. **责任界定**：本项目为开源技术工具，作者不提供任何内容，也不对使用者的任何下载、存储、传播行为承担法律责任。因不当使用产生的一切后果由使用者自行承担。
6. **侵权处理**：如权利人认为本项目存在侵权情形，请通过 GitHub Issue 联系，核实后将及时处理。

---

## 🙏 致谢与衍生关系（Acknowledgements）

本项目是在他人优秀开源成果的基础上完成的，谨此郑重致谢：

### 主要衍生来源

- **[Estecsky/JMBot](https://github.com/Estecsky/JMBot)** —— **本项目（JMBot-Pro）的直接改编来源**。JMBot-Pro 沿用了其“聊天发送 `/jm <id>` → 自动下载 → 生成 PDF → 回传文件”的核心设计与命令交互，并在其基础上扩展了批量下载、JM 账号登录与凭据持久化、群聊 PDF 加密、下载路径可配置、产物自动清理、错误提示优化等功能。在此向原作者致以特别感谢。

### 核心依赖与上游

- **[hect0x7/JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python)**（[MIT License](https://github.com/hect0x7/JMComic-Crawler-Python/blob/master/LICENSE)）—— 提供禁漫站点访问、域名解析、图片混淆还原、账号登录等全部核心下载能力。JMBot-Pro 仅是该库的上层应用，没有它本项目无法成立。
- [Sora-o-tobu/JM-NcatBot](https://github.com/Sora-o-tobu/JM-NcatBot) —— Estecsky/JMBot 的上游项目，本项目的衍生脉络为：
  `JM-NcatBot` → `Estecsky/JMBot` → **JMBot-Pro（本项目）**
- [AstrBot](https://github.com/AstrBotDevs/AstrBot) —— 本项目使用的多平台 LLM 聊天机器人框架
- [NapCatQQ](https://napcat.napneko.icu/) —— QQ 协议端
- [NcatBot](https://docs.ncatbot.xyz/) —— 姊妹仓库 [JMBot-NcatBot](https://github.com/Sanshui755/JMBot-NcatBot) 所使用的 Python 机器人框架

> **许可说明**：[Estecsky/JMBot](https://github.com/Estecsky/JMBot) 与 Sora-o-tobu/JM-NcatBot 未在其仓库中声明开源许可证。本项目在充分署名的前提下发布衍生代码，若相关权利人对改编或发布有异议，请随时联系，将第一时间配合处理。

---

## 功能特性

- `/jm <id>` 下载漫画并生成 PDF 回传（群聊 / 私聊）
- **批量下载**：`/jm 350234 350235 350236`，或一条消息内包含多条 `/jm` 指令；兼容 `/jm350234`（无空格）、`/jm 350234备注`（数字后紧跟文字）等写法
- **超分辨率下载（双模型可选）**：对下载图片逐张超分辨率放大后再合并 PDF，画质提升明显；两套工具均为 ncnn-vulkan 预编译二进制，无需安装 torch 等重型依赖（使用前请注意下方⚠️警告）
  - `/jm -h <id>`：使用插件配置页选定的默认模型（默认 Real-ESRGAN）
  - `/jm -hr <id>`：强制用 Real-ESRGAN（anime 模型，4x 放大，工具包约 45MB）
  - `/jm -hw <id>`：强制用 waifu2x（cunet 动漫模型，降噪级别 2，2x 放大，工具包约 35MB）
- **站内搜索**：`/jms <关键词>` 按关键词搜索本子，每页 10 条结果（车号、标题、标签），兼容 `/jms关键词` 无空格写法；结果末尾回复 `1` 看下一页、`0` 退出，5 分钟内仅搜索发起人本人操作有效
- **作者搜索**：`/jma <作者名>` 按作者搜索本子，每页 10 条，兼容 `/jma作者名` 无空格写法，翻页方式同 `/jms`
- **本子详情查询**：`/jmv <任意文本>` 只查不下载，自动从粘贴的链接或整段文本中提取车号，返回标题、作者、标签、观看数等信息，适合先确认车号内容再决定是否下载
- **JM 账号登录**：通过聊天指令保存账号凭据（仅存于本机），启动时自动登录，可获取仅对登录用户可见的内容；凭据不会被收集或上传
- **PDF 加密**：群聊回传的 PDF 可自动添加打开密码（私聊默认不加密）
- **下载路径可配置**：支持 WebUI / 聊天指令 / 配置文件修改，切换目录时旧文件自动迁移
- **自动清理**：下载产物默认保留 3 天，过期后由后台任务自动删除（每 6 小时执行一次）
- **错误处理**：本子不存在、ID 错误等场景返回明确的中文提示，异常详情写入本地日志
- **登录测试**：WebUI 配置页保存 JM 账号后插件自动热重载并立即测试登录，结果在 WebUI「日志」页查看
- 启动登录在后台执行，不阻塞消息处理

> [!WARNING]
> **超分辨率下载代价较高，请按需使用：**
>
> - **耗时显著增加**：需对每一页图片逐张放大，页数越多越慢。有独显（Vulkan）时较快；无独显会回退到 CPU 运算，单本可能耗时数十分钟，请耐心等待、不要重复发送指令。
> - **首次使用需联网下载工具包**：Real-ESRGAN 约 45MB / waifu2x 约 35MB，仅首次自动下载一次，存放在插件数据目录，之后离线可用。
> - **磁盘占用增大**：放大后的图片分辨率与体积成倍增长（4x 约为原像素量的 16 倍），最终 PDF 也会明显变大，请确保下载盘有充足空间。
> - **不要对批量本子统一使用超分**：建议只对确实需要提升画质的单本使用；超分产物同样在 3 天后自动清理。

---

## 安装与使用（NapCat + AstrBot 插件）

架构链路：**QQ ← NapCat（QQ 协议端）← aiocqhttp → AstrBot（机器人框架）← 插件 → JMBot**。

[ AstrBot ](https://github.com/AstrBotDevs/AstrBot)是一个开源的多平台 LLM 聊天机器人框架，自带 WebUI 管理界面。以插件方式安装本项目是**最简单的使用方式**：不需要写配置文件、不需要命令行、超管和各项开关都在网页上填写。

### 前置条件

- 已安装并运行 [NapCat](https://napcat.napneko.icu/)（QQ 协议端，用于接入 QQ 消息）
- 已安装并运行 [AstrBot](https://github.com/AstrBotDevs/AstrBot)（官方文档：[astrbot.app](https://astrbot.app)），并通过 aiocqhttp 适配器接入 NapCat

### 安装步骤

1. 下载本仓库，将 `astrbot_plugin_jmbot` 目录打包为 zip。**注意：zip 根目录必须是单一的 `astrbot_plugin_jmbot/` 文件夹**，不能将内部文件直接散放在压缩包根层（也可以直接在 [Releases](../../releases) 下载打包好的 zip）。
2. 进入 AstrBot WebUI → **插件管理** → 上传 zip 安装（Python 依赖将自动安装）。
3. 在插件管理 → **JMBot → 配置**中填写：
   - **超管 QQ 号**（必填，不知道自己的 ID 可先在聊天里发送 `/sid` 获取）
   - 群聊下载开关、群聊 PDF 加密、PDF 密码
   - 下载文件保存路径（留空则使用默认的 `用户目录\JMBot-Downloads`）
4. 保存后重载插件，即可使用。

详细配置说明见插件目录下的 [README](astrbot_plugin_jmbot/README.md)。

### 快速验证

私聊机器人依次发送：

```
设置JM账号 你的用户名
设置JM密码 你的密码
JM状态
/jm 350234
```

群聊使用前，先由超管私聊机器人发送 `开启JMBot`。

---

## 其他部署方式：NcatBot 独立版

如果你希望运行一个**独立、轻量、不依赖 AstrBot** 的机器人（NapCat + NcatBot 架构），请使用姊妹仓库 **[Sanshui755/JMBot-NcatBot](https://github.com/Sanshui755/JMBot-NcatBot)**，其中包含独立的安装与配置说明。

> 注：NcatBot 独立版仅保留 `/jm` 下载核心与管理命令；站内搜索（`/jms`、`/jma`）、详情查询（`/jmv`）、超分辨率下载（`-h/-hr/-hw`）、WebUI 进度页等为 AstrBot 插件版独有。

---

## 目录结构

```
JMBot-Pro
└── astrbot_plugin_jmbot/      # NapCat + AstrBot 插件
    ├── main.py                #   插件本体
    ├── _conf_schema.json      #   WebUI 配置项定义
    ├── metadata.yaml          #   插件元数据
    ├── pages/progress/        #   WebUI 实时下载进度页
    └── ...
```

敏感配置（`jm_account.json`、`pdf_password.txt` 等）与下载产物均不会进入版本库，详见 [`.gitignore`](.gitignore)。

---

## 常见问题

- **想要不依赖 AstrBot 的独立机器人？** 请使用姊妹仓库 [JMBot-NcatBot](https://github.com/Sanshui755/JMBot-NcatBot)（NapCat + NcatBot）。
- **提示域名解析失败**：JM 域名可能因网络环境无法解析。jmcomic 会自动获取可用域名；必要时可在 jmcomic 配置的 `client.domain` 中手动指定可用域名，或为终端配置代理。
- **登录返回 401**：请核对账号与密码，并确保每条设置命令单独发送。
- **群聊中无响应**：群聊下载默认关闭，请先由超管私聊机器人发送 `开启JMBot`。
- **修改代码后不生效**：在 AstrBot WebUI 中重载插件即可。

---

## 开发说明

**JMBot-Pro 的全部代码由 [Trae](https://www.trae.ai/)（AI 编程助手）辅助完成**：由使用者提出需求与测试反馈，Trae 负责方案分析、代码编写与缺陷修复，经多轮迭代形成当前版本。项目架构与功能规划由使用者决定。

---

## 许可证（License）

- 本项目**新增与改编的代码**以 [MIT License](LICENSE) 开源。
- 核心依赖 [JMComic-Crawler-Python](https://github.com/hect0x7/JMComic-Crawler-Python) 遵循其自身的 MIT License。
- [Estecsky/JMBot](https://github.com/Estecsky/JMBot) 及 [Sora-o-tobu/JM-NcatBot](https://github.com/Sora-o-tobu/JM-NcatBot) 未声明开源许可证，本项目对其保持完整署名；如权利人有异议，请联系处理。
- 本项目不包含任何受版权保护的漫画内容。
