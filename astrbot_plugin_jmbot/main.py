"""
JMBot —— AstrBot 版禁漫下载插件

群聊 / 私聊发送 ``/jm <id>``，机器人自动下载相册、生成 PDF 并发送文件。
支持批量：``/jm 350234 350235`` 或一条消息内多条 ``/jm`` 指令，
数字后紧跟中文备注（如 ``/jm 350234极品``）也能正确识别。
下载产物（stock/pdf/encrypt_pdf）统一保存在「下载路径」下的三个子文件夹中，
默认为用户目录下的 JMBot-Downloads（Windows: C:\\Users\\你\\JMBot-Downloads），
可用超管私聊命令「设置下载路径 xxx」修改；
仅在本机保留 3 天，到期自动删除。
管理命令（仅配置的超管，私聊发送）：开启JMBot / 关闭JMBot / 测试JMBot /
打开加密 / 关闭加密 / PDF密码 / 设置PDF密码 xxx /
下载路径 / 设置下载路径 xxx /
设置JM账号 xxx / 设置JM密码 xxx / JM登录 / JM状态 / 清除JM账号 / JM帮助

移植自 ncatbot5 版 JMBot，逻辑与原版一致。
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path

import jmcomic
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from jmcomic.jm_exception import MissingAlbumPhotoException

from .set_password import set_password_pdf

PLUGIN_DIR = Path(__file__).resolve().parent
JM_CONFIG_TEMPLATE = PLUGIN_DIR / "config.yml"

HELP_TEXT = (
    "使用方法：\n输入 /jm+空格+id ，机器人会自动下载生成 pdf 并发送消息。\n"
    "例： /jm 350234\n"
    "支持批量： /jm 350234 350235（或一条消息里发多条 /jm 指令）\n"
    "数字后加中文备注也可以，如 /jm 350234极品\n"
    "下载的文件仅在本机保留3天，到期自动删除\n"
    "如有pdf有密码,默认密码为114514"
)

ADMIN_HELP_TEXT = (
    "超管命令：\n"
    "下载路径（查看当前下载目录）\n"
    "设置下载路径 D:\\xxx（修改下载目录，自动迁移旧文件）\n"
    "设置JM账号 用户名\n"
    "设置JM密码 密码\n"
    "JM登录（立即登录）\n"
    "JM状态（查看账号与登录状态）\n"
    "清除JM账号（删除已保存的账号密码）"
)

# 本子不存在 / 不可访问时发送给用户的友好提示（{album} 会替换为本子 id）
ALBUM_NOT_FOUND_TEXT = (
    "请求的本子不存在！(https://18comic.vip/album/{album}/)\n"
    "原因可能为:\n"
    "1. id有误，检查你的本子id\n"
    "2. 该漫画不存在"
)

# ---------------- 下载产物自动清理 ----------------
# 下载路径下的三个产物子文件夹
CLEANUP_DIRS = ("stock", "pdf", "encrypt_pdf")
# 文件保留时长：3 天
CLEANUP_KEEP_SECONDS = 3 * 24 * 60 * 60
# 自动清理执行间隔：6 小时
CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60
# 默认下载路径（其下自动创建 stock/pdf/encrypt_pdf；可在配置或聊天命令中修改）
# 默认保存到用户目录下的 JMBot-Downloads，例如 Windows: C:\Users\你\JMBot-Downloads
DEFAULT_DOWNLOAD_ROOT = str(Path.home() / "JMBot-Downloads")
# 历史版本使用过的下载根目录（如需从旧目录自动迁移，把旧目录填到这里即可）
LEGACY_DOWNLOAD_ROOTS: tuple[str, ...] = ()


@register("astrbot_plugin_jmbot", "Sanshui755", "禁漫下载插件，批量下载/路径可配/自动清理", "1.3.5", "")
class JMBot(Star):
    """JMBot 插件"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        # WebUI 可视化配置（超管QQ / 群开关 / PDF加密 / PDF密码）
        self.config = config if config is not None else {}

        # AstrBot 为插件分配的持久化数据目录（data/plugin_data/<plugin_name>/）
        self.data_dir: Path = (
            Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_jmbot"
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # 运行时文件路径（账号、jmcomic 配置仍留在插件数据目录）
        self.jm_config_path = self.data_dir / "config.yml"
        self.jm_account_path = self.data_dir / "jm_account.json"

        # 下载路径（其下自动创建 stock/pdf/encrypt_pdf）
        self.download_root.mkdir(parents=True, exist_ok=True)

        # JM 账号状态
        self.jm_username: str = ""
        self.jm_password: str = ""
        self.jm_logged_in: bool = False
        self.jm_cred_source: str = "无"  # 无 / 本地保存 / WebUI 配置
        self._background_tasks: set = set()
        # 已收到过"无权限"提示的私聊用户，每人只提示一次
        self._no_permission_notified: set[str] = set()

        # 后台把历史下载目录（旧版本布局）迁到当前路径
        self._migration_task = asyncio.create_task(
            asyncio.to_thread(self._migrate_old_downloads)
        )
        self._background_tasks.add(self._migration_task)
        self._migration_task.add_done_callback(self._background_tasks.discard)

        self._prepare_jm_option()
        self._load_jm_account()

        if not self.super_user:
            logger.warning("未配置超管 QQ，请在 AstrBot 管理面板的 JMBot 插件配置中填写")

        # 已保存 JM 账号则后台自动登录；不阻塞插件加载
        if self.jm_username and self.jm_password:
            task = asyncio.create_task(self._jm_login())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        # 启动下载产物自动清理任务（先清理一次，之后每隔 6 小时清理）
        cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._background_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._background_tasks.discard)

        logger.info("JMBot v1.3.5 已加载（指令消息已隔离：屏蔽默认 LLM 与陪伴/记忆插件）")
        logger.info(f"JMBot 插件超管: {self.super_user or '(未配置)'}")
        logger.info(f"JMBot 下载目录: {self.download_root}")

    # ------------------------------------------------------------------
    # WebUI 配置项
    # ------------------------------------------------------------------

    @property
    def super_user(self) -> str:
        return str(self.config.get("super_user_id", "")).strip()

    @property
    def download_root(self) -> Path:
        """下载路径，其下自动创建 stock/pdf/encrypt_pdf 三个文件夹。"""
        raw = str(self.config.get("download_root", "")).strip()
        return Path(raw) if raw else Path(DEFAULT_DOWNLOAD_ROOT)

    @property
    def jm_on(self) -> bool:
        return bool(self.config.get("group_enabled", False))

    @jm_on.setter
    def jm_on(self, value: bool) -> None:
        self.config["group_enabled"] = bool(value)
        self._save_config()

    @property
    def pdf_encrypt(self) -> bool:
        return bool(self.config.get("pdf_encrypt", True))

    @pdf_encrypt.setter
    def pdf_encrypt(self, value: bool) -> None:
        self.config["pdf_encrypt"] = bool(value)
        self._save_config()

    @property
    def pdf_password(self) -> str:
        return str(self.config.get("pdf_password", ""))

    @pdf_password.setter
    def pdf_password(self, value: str) -> None:
        self.config["pdf_password"] = value
        self._save_config()

    def _save_config(self) -> None:
        """保存 WebUI 配置（直接修改文件的场景需要手动落盘）。"""
        save = getattr(self.config, "save_config", None)
        if callable(save):
            try:
                save()
            except Exception as e:
                logger.warning(f"插件配置保存失败: {e}")

    # ------------------------------------------------------------------
    # 初始化辅助
    # ------------------------------------------------------------------

    def _prepare_jm_option(self) -> None:
        """生成本次运行使用的 jmcomic 配置，图片/PDF 路径指向 download_root。"""
        stock_dir = self.download_root / "stock"
        pdf_dir = self.download_root / "pdf"
        stock_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        text = JM_CONFIG_TEMPLATE.read_text(encoding="utf-8")
        text = text.replace("base_dir: stock", f"base_dir: {stock_dir}")
        text = text.replace("img_dir: stock", f"img_dir: {stock_dir}")
        text = text.replace("pdf_dir: pdf", f"pdf_dir: {pdf_dir}")
        self.jm_config_path.write_text(text, encoding="utf-8")
        self.jm_option = jmcomic.JmOption.from_file(str(self.jm_config_path))
        # 三个产物文件夹统一在下载路径下自动创建
        (self.download_root / "encrypt_pdf").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # JM 账号：本地保存 / 读取 / 登录
    # ------------------------------------------------------------------

    def _load_jm_account(self) -> None:
        """读取 JM 账号密码：WebUI 插件配置优先，其次 data/jm_account.json。"""
        self.jm_cred_source = "无"
        try:
            data = json.loads(self.jm_account_path.read_text(encoding="utf-8"))
            self.jm_username = str(data.get("username", "")).strip()
            self.jm_password = str(data.get("password", ""))
            if self.jm_username and self.jm_password:
                self.jm_cred_source = "本地保存"
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"JM 账号文件读取失败: {e}")
        # WebUI 插件配置中的 JM 账号密码优先于本地保存
        cfg_user = str(self.config.get("jm_username") or "").strip()
        cfg_pass = str(self.config.get("jm_password") or "")
        if cfg_user and cfg_pass:
            self.jm_username, self.jm_password = cfg_user, cfg_pass
            self.jm_cred_source = "WebUI 配置"
            logger.info("JM 账号已从 WebUI 插件配置读取（优先于本地保存）")

    def _save_jm_account(self) -> None:
        """把 JM 账号密码写入本地文件。"""
        self.jm_account_path.parent.mkdir(parents=True, exist_ok=True)
        self.jm_account_path.write_text(
            json.dumps(
                {"username": self.jm_username, "password": self.jm_password},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _jm_login_sync(self) -> None:
        """同步登录 JM 并把 cookies 写入 option（在线程中调用）。"""
        if not self.jm_username or not self.jm_password:
            raise ValueError("尚未保存 JM 账号或密码")
        client = self.jm_option.build_jm_client()
        client.login(self.jm_username, self.jm_password)
        # 登录后的 cookies 写入 option，后续下载 client 自动携带
        self.jm_option.update_cookies(dict(client["cookies"]))

    async def _jm_login(self) -> tuple[bool, str]:
        """执行 JM 登录，返回 (是否成功, 提示消息)。"""
        try:
            await asyncio.to_thread(self._jm_login_sync)
            self.jm_logged_in = True
            logger.info(f"JM 登录成功，账号: {self.jm_username}")
            return True, f"JM 登录成功，当前账号：{self.jm_username}"
        except Exception as e:
            self.jm_logged_in = False
            logger.warning(f"JM 登录失败: {e}")
            return False, f"JM 登录失败：{e}"

    async def _ensure_jm_login(self) -> None:
        """下载前兜底：已保存账号但未登录时自动登录一次。"""
        if self.jm_username and self.jm_password and not self.jm_logged_in:
            ok, msg = await self._jm_login()
            logger.info(f"下载前自动登录: {msg}")

    # ------------------------------------------------------------------
    # /jm 下载指令（正式注册，群聊/私聊均可触发）
    # ------------------------------------------------------------------

    @staticmethod
    def _claim(event: AstrMessageEvent) -> None:
        """JMBot 认领该消息：禁止默认 LLM 链路，并打上认领标记。

        认领标记供外层包装函数在回复发送完毕后调用 stop_event()，
        终止事件传播，防止陪伴/记忆类插件（private_companion、
        self_learning、memory_companion 等）再次回复本指令并把
        指令内容写入长期记忆。
        """
        event.should_call_llm(True)
        event.set_extra("jmbot_claimed", True)

    @filter.command("jm", priority=500000)
    async def cmd_jm(self, event: AstrMessageEvent, album_id: str = ""):
        """下载禁漫本子：/jm <id>，支持一条消息多个车号。"""
        async for ret in self._cmd_jm_impl(event, album_id):
            yield ret
        # 所有回复均已通过管线发送完毕，此处终止事件传播是安全的
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _cmd_jm_impl(self, event: AstrMessageEvent, album_id: str = ""):
        """下载禁漫本子：/jm <id>，支持一条消息多个车号。"""
        # 指令消息归 JMBot 处理：禁止 AstrBot 默认 LLM 再把指令当聊天回复一遍
        self._claim(event)
        user_id = str(event.get_sender_id())
        is_group = not event.is_private_chat()

        if is_group and not self.jm_on:
            # 群聊开关关闭：静默忽略，避免打扰群聊
            return

        # 从消息原文解析全部车号（/jm a b、多条 /jm、数字后带中文备注均支持）
        album_ids = self._parse_album_ids(event.message_str)
        if not album_ids:
            yield event.plain_result(HELP_TEXT)
            return

        total = len(album_ids)
        id_preview = "、".join(album_ids)
        yield event.plain_result(f"开始下载 {total} 个本子：{id_preview}，请稍候……")

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []

        for aid in album_ids:
            try:
                file_path = await self._fetch_pdf(aid)
                # 群聊按配置加密；私聊不加密
                if is_group and self.pdf_encrypt:
                    file_path = await self._encrypt_pdf(aid, file_path)
                yield event.chain_result([File(file=file_path, name=f"{aid}.pdf")])
                succeeded.append(aid)
            except Exception as e:
                logger.exception(f"/jm 下载本子 {aid} 失败: {e}")
                failed.append((aid, self._format_download_error(aid, e)))

        # 单个车号：保持旧行为，失败才提示，成功不打扰
        if total == 1:
            if failed:
                yield event.plain_result(failed[0][1])
            return

        # 多个车号：发送一条汇总
        lines = [f"批量下载完成：成功 {len(succeeded)} 个，失败 {len(failed)} 个"]
        for aid, reason in failed:
            lines.append(f"{aid}：{reason}")
        yield event.plain_result("\n".join(lines))

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE,
        priority=500000,
    )
    async def on_jm_nospace(self, event: AstrMessageEvent):
        """兜底：识别无空格写法 ``/jm350234``。"""
        async for ret in self._on_jm_nospace_impl(event):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _on_jm_nospace_impl(self, event: AstrMessageEvent):
        """兜底：识别无空格写法 ``/jm350234``。

        标准指令过滤器只认 ``jm`` 后接空格/结尾，``jm350234``（群聊唤醒
        前缀 ``/`` 被剥掉）或私聊原文 ``/jm350234`` 都不会命中指令处理器，
        这里统一接住并解析。
        """
        text = (event.message_str or "").strip()
        if not re.match(r"/?jm\d+", text, re.IGNORECASE):
            return

        # 命中 jm 车号形态，同样禁止默认 LLM 响应
        self._claim(event)

        album_ids = self._parse_album_ids(text)
        if not album_ids:
            return

        is_group = not event.is_private_chat()
        if is_group and not self.jm_on:
            return

        total = len(album_ids)
        id_preview = "、".join(album_ids)
        yield event.plain_result(f"开始下载 {total} 个本子：{id_preview}，请稍候……")

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []
        for aid in album_ids:
            try:
                file_path = await self._fetch_pdf(aid)
                if is_group and self.pdf_encrypt:
                    file_path = await self._encrypt_pdf(aid, file_path)
                yield event.chain_result([File(file=file_path, name=f"{aid}.pdf")])
                succeeded.append(aid)
            except Exception as e:
                logger.exception(f"/jm(无空格) 下载本子 {aid} 失败: {e}")
                failed.append((aid, self._format_download_error(aid, e)))

        if total == 1:
            if failed:
                yield event.plain_result(failed[0][1])
            return
        lines = [f"批量下载完成：成功 {len(succeeded)} 个，失败 {len(failed)} 个"]
        for aid, reason in failed:
            lines.append(f"{aid}：{reason}")
        yield event.plain_result("\n".join(lines))

    # ------------------------------------------------------------------
    # 群聊超管命令（与 ncatbot 版一致：测试/开启/关闭）
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE, priority=500000)
    async def on_group_admin(self, event: AstrMessageEvent):
        async for ret in self._on_group_admin_impl(event):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _on_group_admin_impl(self, event: AstrMessageEvent):
        text = (event.message_str or "").strip()
        user_id = str(event.get_sender_id())
        if not self._check_admin(user_id):
            return

        # 命中群聊管理命令时禁止默认 LLM 响应
        if text in ("测试JMBot", "关闭JMBot", "开启JMBot"):
            self._claim(event)

        if text == "测试JMBot":
            yield event.plain_result("插件JMBot测试成功")
        elif text == "关闭JMBot":
            self.jm_on = False
            yield event.plain_result("JMBot已关闭")
        elif text == "开启JMBot":
            self.jm_on = True
            yield event.plain_result("JMBot已打开")

    # ------------------------------------------------------------------
    # 私聊管理命令（仅超管）
    # ------------------------------------------------------------------

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=500000)
    async def on_private_message(self, event: AstrMessageEvent):
        async for ret in self._on_private_message_impl(event):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _on_private_message_impl(self, event: AstrMessageEvent):
        text = event.message_str
        user_id = str(event.get_sender_id())
        logger.info(f"私聊消息: {text} (from {user_id})")

        # /jm 下载指令交给指令处理器与无空格兜底处理器，这里不重复处理
        # （/jm、/jm 350234、/jm350234 均跳过；JM状态/JM帮助 等中文命令不受影响）
        if re.match(r"/?jm(?:\s|\d|$)", text, re.IGNORECASE):
            return

        # 以下管理命令仅超管可用：非超管对任何其他消息只提示一次，避免刷屏
        if not self._check_admin(user_id):
            if user_id not in self._no_permission_notified:
                self._no_permission_notified.add(user_id)
                self._claim(event)
                yield event.plain_result("你没有权限使用该命令，发送 /jm help 查看用法")
            return

        # 超管：归一化命令（JM 大小写、"登陆"错字），让下方分支稳定命中
        text = re.sub(r"(?i)^jm", "JM", text.strip()).replace("登陆", "登录")

        # 以 JM 开头或命中已知管理命令的消息一律认领：禁止默认 LLM 响应，
        # 即使命令拼写有误也由插件兜底提示，不落进 AI 聊天
        first_line = text.splitlines()[0].strip()
        if first_line.startswith("JM") or first_line.startswith(
            ("设置PDF密码", "设置下载路径", "设置JM账号", "设置JM密码")
        ) or first_line in (
            "打开加密", "关闭加密", "PDF密码", "下载路径",
        ):
            self._claim(event)

        if text == "测试JMBot":
            yield event.plain_result("JMBot测试成功")
            return

        if text == "打开加密":
            self.pdf_encrypt = True
            yield event.plain_result("JMBot加密已打开")
            return

        if text == "关闭加密":
            self.pdf_encrypt = False
            yield event.plain_result("JMBot加密已关闭")
            return

        if text == "PDF密码":
            yield event.plain_result(self.pdf_password)
            return

        if text.startswith("设置PDF密码"):
            first_line = text.splitlines()[0]
            parts = first_line.split(maxsplit=1)
            new_password = parts[1].strip() if len(parts) > 1 else ""
            if not new_password:
                yield event.plain_result("用法：设置PDF密码 密码")
                return
            self.pdf_password = new_password
            yield event.plain_result("PDF密码设置成功")
            return

        if text == "下载路径":
            yield event.plain_result(
                f"当前下载路径：{self.download_root}\n"
                f"其下自动维护 stock（原图）、pdf、encrypt_pdf（加密PDF）三个文件夹。\n"
                f"修改请发送：设置下载路径 D:\\xxx"
            )
            return

        if text.startswith("设置下载路径"):
            first_line = text.splitlines()[0]
            parts = first_line.split(maxsplit=1)
            new_path = parts[1].strip().strip('"') if len(parts) > 1 else ""
            if not new_path:
                yield event.plain_result("用法：设置下载路径 F:\\xxx（不要带引号）")
                return
            yield event.plain_result(await self._apply_download_root(new_path))
            return

        if text == "关闭JMBot":
            self.jm_on = False
            yield event.plain_result("JMBot已关闭")
            return

        if text == "开启JMBot":
            self.jm_on = True
            yield event.plain_result("JMBot已打开")
            return

        # ---------------- JM 账号管理 ----------------

        if text == "JM帮助":
            yield event.plain_result(ADMIN_HELP_TEXT)
            return

        if text.startswith("设置JM账号"):
            first_line = text.splitlines()[0]
            parts = first_line.split(maxsplit=1)
            username = parts[1].strip() if len(parts) > 1 else ""
            if not username:
                yield event.plain_result("用法：设置JM账号 用户名")
                return
            self.jm_username = username
            self.jm_cred_source = "本地保存"
            self._save_jm_account()
            self.jm_logged_in = False
            tip = ""
            if (str(self.config.get("jm_username") or "").strip()
                    and str(self.config.get("jm_password") or "")):
                tip = "\n注意：WebUI 插件配置中也填有 JM 账号，重启后将以 WebUI 配置优先。"
            yield event.plain_result(f"JM 账号已保存：{username}，请继续发送\"设置JM密码 密码\"{tip}")
            return

        if text.startswith("设置JM密码"):
            first_line = text.splitlines()[0]
            parts = first_line.split(maxsplit=1)
            password = parts[1].strip() if len(parts) > 1 else ""
            if not password:
                yield event.plain_result("用法：设置JM密码 密码")
                return
            self.jm_password = password
            self.jm_cred_source = "本地保存"
            self._save_jm_account()
            self.jm_logged_in = False
            yield event.plain_result("JM 密码已保存，正在尝试登录……")
            _, msg = await self._jm_login()
            yield event.plain_result(msg)
            return

        if text == "JM登录":
            if not self.jm_username or not self.jm_password:
                yield event.plain_result(
                    "请先在 WebUI 插件配置中填写 JM 账号密码，"
                    "或发送\"设置JM账号 用户名\"和\"设置JM密码 密码\""
                )
                return
            yield event.plain_result("正在登录 JM……")
            _, msg = await self._jm_login()
            yield event.plain_result(msg)
            return

        if text == "JM状态":
            if not self.jm_username:
                status = "未保存 JM 账号（可在 WebUI 插件配置中填写，或发送\"设置JM账号 用户名\"）"
            else:
                status = (
                    f"账号：{self.jm_username}\n"
                    f"账号来源：{self.jm_cred_source}\n"
                    f"登录状态：{'已登录' if self.jm_logged_in else '未登录'}"
                )
            yield event.plain_result(status)
            return

        if text == "清除JM账号":
            self.jm_username = ""
            self.jm_password = ""
            self.jm_logged_in = False
            self.jm_cred_source = "无"
            try:
                self.jm_account_path.unlink()
            except FileNotFoundError:
                pass
            msg = "已清除保存的 JM 账号密码"
            if (str(self.config.get("jm_username") or "").strip()
                    and str(self.config.get("jm_password") or "")):
                msg += "\n注意：WebUI 插件配置中仍填有 JM 账号，重启插件后将继续使用；如需彻底清除请在 WebUI 中清空。"
            yield event.plain_result(msg)
            return

        # 兜底：认领了 JMBot 命令但未命中任何已知命令（如拼写有误），
        # 直接提示正确用法，不交给默认 LLM 回复
        if event.get_extra("jmbot_claimed"):
            yield event.plain_result(
                f"未知的 JMBot 命令：{first_line}\n发送 JM帮助 查看所有命令"
            )

    def _check_admin(self, user_id: str) -> bool:
        """判断发送者是否为配置的超管。"""
        return bool(self.super_user) and user_id == self.super_user

    # ------------------------------------------------------------------
    # 业务逻辑
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_album_ids(text: str) -> list[str]:
        """从消息原文解析全部本子 id。

        支持的写法（可跨行、大小写不敏感，斜杠可有可无）：
        - ``/jm 350234 350235``（一个指令多个车号）
        - ``/jm 350234 /jm 350235``（一条消息多个指令）
        - ``/jm350234``（无空格也可识别）
        - ``/jm 350234极品``（数字后紧跟中文等字符，只取数字前缀）

        ``jm`` 必须位于消息开头或空白之后（斜杠可有可无），且后面紧跟
        空白/数字/结尾，避免误匹配 x/jm 5、jmusic 等普通单词。
        每个 ``jm`` 之后逐 token 读取开头的连续数字，遇到第一个不以
        数字开头的 token 即停止（``/jm help`` 等不会被当成车号）。
        结果去重并保序。
        """
        album_ids: list[str] = []
        pattern = r"(?:^|(?<=\s))/?jm(?=\s|\d|$)"
        for segment in re.split(pattern, text, flags=re.IGNORECASE)[1:]:
            for token in segment.split():
                match = re.match(r"\d+", token)
                if match:
                    album_ids.append(match.group())
                else:
                    break
        # 去重并保持原顺序
        return list(dict.fromkeys(album_ids))

    @staticmethod
    def _format_download_error(album_id: str, e: Exception) -> str:
        """把下载阶段的异常转换为发给用户的友好提示。"""
        if isinstance(e, MissingAlbumPhotoException):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        if isinstance(e, FileNotFoundError) and "未找到生成的 PDF" in str(e):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        return f"下载/发送失败：{e}"

    async def _fetch_pdf(self, album_id: str) -> str:
        """下载相册并生成 PDF，返回 PDF 绝对路径。"""
        await self._ensure_jm_login()

        def _download() -> None:
            self.jm_option.download_album([album_id])

        await asyncio.to_thread(_download)
        pdf_path = self.download_root / "pdf" / f"{album_id}.pdf"
        if not pdf_path.exists():
            raise FileNotFoundError(f"未找到生成的 PDF: {pdf_path}")
        return str(pdf_path.resolve())

    async def _encrypt_pdf(self, album_id: str, src_pdf: str) -> str:
        """加密 PDF，返回加密后文件的绝对路径。"""
        out_dir = self.download_root / "encrypt_pdf"
        out_dir.mkdir(parents=True, exist_ok=True)
        dst_path = out_dir / f"{album_id}_encrypt.pdf"

        await asyncio.to_thread(
            set_password_pdf, src_pdf, str(dst_path), self.pdf_password
        )
        return str(dst_path.resolve())

    # ------------------------------------------------------------------
    # 旧下载目录迁移 & 下载产物自动清理（保留 3 天）
    # ------------------------------------------------------------------

    def _legacy_download_roots(self, extra: list[Path] | None = None) -> list[Path]:
        """返回所有历史下载根目录（去重、排除当前下载路径）。"""
        candidates = [self.data_dir]
        candidates.extend(Path(p) for p in LEGACY_DOWNLOAD_ROOTS)
        if extra:
            candidates.extend(extra)

        result: list[Path] = []
        seen: set[str] = set()
        try:
            current = self.download_root.resolve()
        except OSError:
            current = self.download_root
        for root in candidates:
            try:
                resolved = root.resolve()
                if resolved == current:
                    continue
                key = str(resolved).lower()
            except OSError:
                key = str(root).lower()
            if key not in seen:
                seen.add(key)
                result.append(root)
        return result

    async def _apply_download_root(self, new_path: str) -> str:
        """运行时修改下载路径：保存配置、重建三个文件夹与 jm 配置、后台迁移旧文件。"""
        old_root = self.download_root
        target = Path(new_path)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"下载路径设置失败，无法创建目录：{e}"

        self.config["download_root"] = str(target)
        self._save_config()
        # 重建 jmcomic 配置（图片/PDF 输出指向新路径下的 stock/pdf）
        self._prepare_jm_option()

        task = asyncio.create_task(
            asyncio.to_thread(
                self._migrate_old_downloads, [old_root]
            )
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        logger.info(f"JMBot 下载路径已切换: {old_root} -> {target}")
        return (
            f"下载路径已设置为：{target}\n"
            "已自动创建 stock/pdf/encrypt_pdf 三个文件夹，"
            "旧路径的文件正在后台迁移，请留意日志。"
        )

    def _migrate_old_downloads(self, extra_roots: list[Path] | None = None) -> None:
        """把各历史下载根目录中的 stock/pdf/encrypt_pdf 合并迁移到当前下载路径。

        - 与当前路径相同的目录自动跳过；
        - 目标已存在同名项时保留新位置的文件，删除旧项；
        - 迁移保留文件原始修改时间（shutil.move 跨盘复制也会保留 mtime）。
        """
        for legacy_root in self._legacy_download_roots(extra_roots):
            for dirname in CLEANUP_DIRS:
                old_dir = legacy_root / dirname
                if not old_dir.exists():
                    continue

                new_dir = self.download_root / dirname
                new_dir.mkdir(parents=True, exist_ok=True)
                moved = 0
                for item in old_dir.iterdir():
                    target = new_dir / item.name
                    try:
                        if target.exists():
                            # 新位置已有同名内容（可能是刚下载的），丢弃旧项
                            if item.is_dir():
                                shutil.rmtree(item, ignore_errors=True)
                            else:
                                item.unlink()
                        else:
                            shutil.move(str(item), str(target))
                            moved += 1
                    except OSError as e:
                        logger.warning(f"JMBot 迁移 {item} 失败: {e}")
                # 旧目录清空后删除；非空（有迁移失败的残留）则保留，下轮再处理
                try:
                    old_dir.rmdir()
                except OSError:
                    pass
                if moved:
                    logger.info(f"JMBot 已将 {moved} 项旧下载内容迁移到 {new_dir}")

    async def _cleanup_loop(self) -> None:
        """启动时先清理一次，之后每隔 CLEANUP_INTERVAL_SECONDS 清理一次。"""
        # 首次清理前等待旧目录迁移完成（最多等 30 分钟），
        # 使迁移过来的过期文件也能在本轮被清理
        migration = getattr(self, "_migration_task", None)
        if migration is not None:
            try:
                await asyncio.wait_for(asyncio.shield(migration), timeout=1800)
            except asyncio.TimeoutError:
                logger.warning("JMBot 旧目录迁移耗时过长，首次清理不再等待")
            except Exception:
                pass

        while True:
            try:
                removed = await asyncio.to_thread(self._cleanup_old_files)
                if removed:
                    logger.info(
                        f"JMBot 自动清理：已删除 {removed} 个超过 "
                        f"{CLEANUP_KEEP_SECONDS // (24 * 60 * 60)} 天的下载文件"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"JMBot 自动清理失败: {e}")
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    def _cleanup_old_files(self) -> int:
        """删除 download_root 下 stock/pdf/encrypt_pdf 中超过 3 天的文件及空目录。

        依据文件 mtime 判断；正在下载/发送的文件都是刚生成的（mtime 很新），
        不会被误删。返回被删除的文件数量。
        """
        cutoff = time.time() - CLEANUP_KEEP_SECONDS
        removed = 0

        for dirname in CLEANUP_DIRS:
            root = self.download_root / dirname
            if not root.exists():
                continue

            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError:
                    # 文件被占用或权限不足时跳过，下轮再清理
                    pass

            # 删除清理后变空的子目录（自底向上），保留根目录本身
            sub_dirs = (p for p in root.rglob("*") if p.is_dir())
            for path in sorted(sub_dirs, reverse=True):
                try:
                    path.rmdir()
                except OSError:
                    pass

        return removed

    async def terminate(self):
        """插件卸载时清理后台任务。"""
        for task in self._background_tasks:
            task.cancel()
