"""
JMBot —— ncatbot5 版禁漫下载插件

群聊 / 私聊发送 ``/jm <id>``，机器人自动下载相册、生成 PDF 并发送文件。
支持批量：``/jm 350234 350235`` 或一条消息内多条 ``/jm`` 指令。
下载产物（stock/pdf/encrypt_pdf）统一保存在「下载路径」下的三个子文件夹中，
默认 F:\\.jmcomic\\jmcomic，可用超管私聊命令「设置下载路径 xxx」修改；
仅在本机保留 3 天，到期自动删除。
管理命令（仅超管）：开启JMBot / 关闭JMBot / 测试JMBot /
打开加密 / 关闭加密 / PDF密码 / 设置PDF密码 xxx /
下载路径 / 设置下载路径 xxx /
设置JM账号 xxx / 设置JM密码 xxx / JM登录 / JM状态 / 清除JM账号
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from pathlib import Path

import jmcomic
import yaml
from jmcomic.jm_exception import MissingAlbumPhotoException
from ncatbot.core import registrar
from ncatbot.plugin import NcatBotPlugin
from ncatbot.utils import get_log

from .set_password import set_password_pdf

LOG = get_log("JMBot")

PLUGIN_DIR = Path(__file__).resolve().parent
# 机器人根目录（start_all.bat 的工作目录），旧版产物曾在其下的 stock/pdf/encrypt_pdf
# PLUGIN_DIR 已是 plugins/JMBot，parents[0]=plugins、parents[1]=JMBot_v5
BOT_DIR = PLUGIN_DIR.parents[1]
SUPER_USER_PATH = PLUGIN_DIR / "config.yaml"
PASSWORD_PATH = PLUGIN_DIR / "config" / "pdf_password.txt"
# jmcomic 配置模板（相对路径），运行时生成绝对路径版本
JM_CONFIG_TEMPLATE = PLUGIN_DIR / "config" / "config.yml"
JM_CONFIG_RUNTIME = PLUGIN_DIR / "config" / "config_runtime.yml"
# JM 账号密码本地保存文件（明文，仅本机使用）
JM_ACCOUNT_PATH = PLUGIN_DIR / "config" / "jm_account.json"

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
    "2. 该漫画不存在\n"
)

# ---------------- 下载产物自动清理 ----------------
# 下载路径下的三个产物子文件夹：stock/ 图片、pdf/ 生成的 PDF、encrypt_pdf/ 加密 PDF
CLEANUP_DIRS = ("stock", "pdf", "encrypt_pdf")
# 文件保留时长：3 天
CLEANUP_KEEP_SECONDS = 3 * 24 * 60 * 60
# 自动清理执行间隔：6 小时
CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60
# 默认下载路径（其下自动创建 stock/pdf/encrypt_pdf；可在 config.yaml 或聊天命令中修改）
DEFAULT_DOWNLOAD_ROOT = r"F:\.jmcomic\jmcomic"


class JMBot(NcatBotPlugin):
    """JMBot 插件"""

    name = "JMBot"
    version = "1.3.0"

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _init_(self) -> None:
        self.super_user: str = ""
        self.jm_on: bool = False
        self.pdf_encrypt: bool = True
        self.pdf_password: str = ""
        self._load_password()
        # 读取插件配置（超管 / 下载路径）
        self._plugin_config: dict = {}
        self._download_root: Path = Path(DEFAULT_DOWNLOAD_ROOT)
        self._load_plugin_config()
        # 下载路径下自动创建三个产物文件夹
        self.download_root.mkdir(parents=True, exist_ok=True)
        # 生成 jmcomic 运行时配置（图片 -> <路径>/stock，PDF -> <路径>/pdf）
        self._prepare_jm_option()
        # JM 账号状态
        self.jm_username: str = ""
        self.jm_password: str = ""
        self.jm_logged_in: bool = False
        self._background_tasks: set = set()
        # 已收到过"无权限"提示的私聊用户，每人只提示一次
        self._no_permission_notified: set[str] = set()
        self._migration_task = None
        self._load_jm_account()

    @property
    def download_root(self) -> Path:
        """下载路径，其下自动创建 stock/pdf/encrypt_pdf 三个文件夹。"""
        return self._download_root

    def _load_plugin_config(self) -> None:
        """读取 config.yaml（manager_id / download_root）。"""
        try:
            with open(SUPER_USER_PATH, "r", encoding="utf-8") as f:
                self._plugin_config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self._plugin_config = {}
            LOG.warning("插件配置文件不存在: %s", SUPER_USER_PATH)
        self.super_user = str(self._plugin_config.get("manager_id", ""))
        raw = str(self._plugin_config.get("download_root", "")).strip()
        if raw:
            self._download_root = Path(raw)

    def _save_plugin_config(self) -> None:
        """把当前插件配置写回 config.yaml。"""
        SUPER_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SUPER_USER_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(self._plugin_config, f, allow_unicode=True, sort_keys=False)

    def _prepare_jm_option(self) -> None:
        """生成运行时 jmcomic 配置，图片/PDF 输出路径指向当前下载路径。"""
        stock_dir = self.download_root / "stock"
        pdf_dir = self.download_root / "pdf"
        stock_dir.mkdir(parents=True, exist_ok=True)
        pdf_dir.mkdir(parents=True, exist_ok=True)
        text = JM_CONFIG_TEMPLATE.read_text(encoding="utf-8")
        text = text.replace("base_dir: stock", f"base_dir: {stock_dir}")
        text = text.replace("img_dir: stock", f"img_dir: {stock_dir}")
        text = text.replace("pdf_dir: pdf", f"pdf_dir: {pdf_dir}")
        JM_CONFIG_RUNTIME.write_text(text, encoding="utf-8")
        self.jm_option = jmcomic.JmOption.from_file(str(JM_CONFIG_RUNTIME))
        # 三个产物文件夹统一在下载路径下自动创建
        (self.download_root / "encrypt_pdf").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # JM 账号：本地保存 / 读取 / 登录
    # ------------------------------------------------------------------

    def _load_jm_account(self) -> None:
        """从 config/jm_account.json 读取已保存的 JM 账号密码。"""
        try:
            data = json.loads(JM_ACCOUNT_PATH.read_text(encoding="utf-8"))
            self.jm_username = str(data.get("username", "")).strip()
            self.jm_password = str(data.get("password", ""))
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError) as e:
            LOG.warning("JM 账号文件读取失败: %s", e)

    def _save_jm_account(self) -> None:
        """把 JM 账号密码写入本地文件。"""
        JM_ACCOUNT_PATH.parent.mkdir(parents=True, exist_ok=True)
        JM_ACCOUNT_PATH.write_text(
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
            LOG.info("JM 登录成功，账号: %s", self.jm_username)
            return True, f"JM 登录成功，当前账号：{self.jm_username}"
        except Exception as e:
            self.jm_logged_in = False
            LOG.warning("JM 登录失败: %s", e)
            return False, f"JM 登录失败：{e}"

    async def _ensure_jm_login(self) -> None:
        """下载前兜底：已保存账号但未登录时自动登录一次。"""
        if self.jm_username and self.jm_password and not self.jm_logged_in:
            ok, msg = await self._jm_login()
            LOG.info("下载前自动登录: %s", msg)

    def _load_password(self) -> None:
        """从 config/pdf_password.txt 读取 PDF 密码。"""
        try:
            self.pdf_password = PASSWORD_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            LOG.warning("PDF 密码文件不存在: %s", PASSWORD_PATH)
            self.pdf_password = ""

    async def on_load(self) -> None:
        LOG.info("JMBot 插件已加载，超管: %s", self.super_user or "(未配置)")
        LOG.info("JMBot 下载路径: %s", self.download_root)
        # 后台把旧目录（机器人根目录下的 stock/pdf/encrypt_pdf）迁到当前下载路径
        self._migration_task = asyncio.create_task(
            asyncio.to_thread(self._migrate_old_downloads)
        )
        self._background_tasks.add(self._migration_task)
        self._migration_task.add_done_callback(self._background_tasks.discard)
        # 已保存 JM 账号则后台自动登录；不能 await，否则 on_load 期间
        # （网络登录耗时数秒）到达的消息会因插件未就绪而被丢弃
        if self.jm_username and self.jm_password:
            task = asyncio.create_task(self._jm_login())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        # 启动下载产物自动清理任务（先清理一次，之后每隔 6 小时清理）
        cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._background_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._background_tasks.discard)

    # ------------------------------------------------------------------
    # 群消息
    # ------------------------------------------------------------------

    @registrar.qq.on_group_message()
    async def on_group_message(self, event) -> None:
        text = event.raw_message
        user_id = str(event.user_id)
        group_id = event.group_id

        if text == "测试JMBot" and user_id == self.super_user:
            await self.api.qq.post_group_msg(group_id, text="插件JMBot测试成功")
            return

        if text == "关闭JMBot" and user_id == self.super_user:
            self.jm_on = False
            await self.api.qq.post_group_msg(group_id, text="JMBot已关闭")
            return

        if text == "开启JMBot" and user_id == self.super_user:
            self.jm_on = True
            await self.api.qq.post_group_msg(group_id, text="JMBot已打开")
            return

        if text.strip().lower() == "/jm help":
            await self.api.qq.post_group_msg(group_id, text=HELP_TEXT)
            return

        album_ids = self._parse_album_ids(text)
        if album_ids and self.jm_on:
            await self._download_albums(
                album_ids,
                send_msg=lambda t: self.api.qq.post_group_msg(group_id, text=t),
                upload_file=lambda file, name: self.api.qq.file.upload_group_file(
                    group_id, file=file, name=name
                ),
                encrypt=self.pdf_encrypt,
            )

    # ------------------------------------------------------------------
    # 私聊消息（/jm 下载指令所有好友可用，管理命令仅超管）
    # ------------------------------------------------------------------

    @registrar.qq.on_private_message()
    async def on_private_message(self, event) -> None:
        user_id = str(event.user_id)
        text = event.raw_message
        LOG.info("私聊消息: %s (from %s)", text, user_id)

        # /jm 下载指令：所有好友可用（与群聊行为一致），支持一条消息多个车号
        if text.strip().lower() == "/jm help":
            await self.api.qq.post_private_msg(user_id, text=HELP_TEXT)
            return

        album_ids = self._parse_album_ids(text)
        if album_ids:
            await self._download_albums(
                album_ids,
                send_msg=lambda t: self.api.qq.post_private_msg(user_id, text=t),
                upload_file=lambda file, name: self.api.qq.file.upload_private_file(
                    user_id, file=file, name=name
                ),
                # 私聊默认不加密，与旧版行为一致
                encrypt=False,
            )
            return

        # 以下管理命令仅超管可用
        if user_id != self.super_user:
            # 无权限提示每个用户只发一次，避免刷屏
            if user_id not in self._no_permission_notified:
                self._no_permission_notified.add(user_id)
                await self.api.qq.post_private_msg(
                    user_id, text="你没有权限使用该命令，发送 /jm help 查看用法"
                )
            return

        if text == "测试JMBot":
            await self.api.qq.post_private_msg(user_id, text="JMBot测试成功")
            return

        if text == "打开加密":
            self.pdf_encrypt = True
            await self.api.qq.post_private_msg(user_id, text="JMBot加密已打开")
            return

        if text == "关闭加密":
            self.pdf_encrypt = False
            await self.api.qq.post_private_msg(user_id, text="JMBot加密已关闭")
            return

        if text == "PDF密码":
            await self.api.qq.post_private_msg(user_id, text=self.pdf_password)
            return

        if text[:7] == "设置PDF密码":
            new_password = text.splitlines()[0][7:]
            self.pdf_password = new_password
            with open(PASSWORD_PATH, "w", encoding="utf-8") as f:
                f.write(new_password.strip())
            await self.api.qq.post_private_msg(user_id, text="PDF密码设置成功")
            return

        if text == "下载路径":
            await self.api.qq.post_private_msg(
                user_id,
                text=(
                    f"当前下载路径：{self.download_root}\n"
                    "其下自动维护 stock（原图）、pdf、encrypt_pdf（加密PDF）三个文件夹。\n"
                    r"修改请发送：设置下载路径 D:\xxx"
                ),
            )
            return

        if text.startswith("设置下载路径"):
            first_line = text.splitlines()[0]
            parts = first_line.split(maxsplit=1)
            new_path = parts[1].strip().strip('"') if len(parts) > 1 else ""
            if not new_path:
                await self.api.qq.post_private_msg(
                    user_id, text=r"用法：设置下载路径 F:\xxx（不要带引号）"
                )
                return
            msg = self._apply_download_root(new_path)
            await self.api.qq.post_private_msg(user_id, text=msg)
            return

        if text == "关闭JMBot":
            self.jm_on = False
            await self.api.qq.post_private_msg(user_id, text="JMBot已关闭")
            return

        if text == "开启JMBot":
            self.jm_on = True
            await self.api.qq.post_private_msg(user_id, text="JMBot已打开")
            return

        # ---------------- JM 账号管理 ----------------

        if text == "JM帮助":
            await self.api.qq.post_private_msg(user_id, text=ADMIN_HELP_TEXT)
            return

        if text.startswith("设置JM账号"):
            # 只取第一条命令所在行，防止多条指令同消息发送时混入换行内容
            first_line = text.splitlines()[0]
            username = first_line.split(maxsplit=1)[1].strip() if len(first_line.split(maxsplit=1)) > 1 else ""
            if not username:
                await self.api.qq.post_private_msg(
                    user_id, text="用法：设置JM账号 用户名"
                )
                return
            self.jm_username = username
            self._save_jm_account()
            self.jm_logged_in = False
            await self.api.qq.post_private_msg(
                user_id, text=f"JM 账号已保存：{username}，请继续发送“设置JM密码 密码”"
            )
            return

        if text.startswith("设置JM密码"):
            first_line = text.splitlines()[0]
            password = first_line.split(maxsplit=1)[1].strip() if len(first_line.split(maxsplit=1)) > 1 else ""
            if not password:
                await self.api.qq.post_private_msg(
                    user_id, text="用法：设置JM密码 密码"
                )
                return
            self.jm_password = password
            self._save_jm_account()
            self.jm_logged_in = False
            await self.api.qq.post_private_msg(
                user_id, text="JM 密码已保存，正在尝试登录……"
            )
            _, msg = await self._jm_login()
            await self.api.qq.post_private_msg(user_id, text=msg)
            return

        if text == "JM登录":
            if not self.jm_username or not self.jm_password:
                await self.api.qq.post_private_msg(
                    user_id, text="请先发送“设置JM账号 用户名”和“设置JM密码 密码”"
                )
                return
            await self.api.qq.post_private_msg(user_id, text="正在登录 JM……")
            _, msg = await self._jm_login()
            await self.api.qq.post_private_msg(user_id, text=msg)
            return

        if text == "JM状态":
            if not self.jm_username:
                status = "未保存 JM 账号"
            else:
                status = (
                    f"账号：{self.jm_username}\n"
                    f"登录状态：{'已登录' if self.jm_logged_in else '未登录'}"
                )
            await self.api.qq.post_private_msg(user_id, text=status)
            return

        if text == "清除JM账号":
            self.jm_username = ""
            self.jm_password = ""
            self.jm_logged_in = False
            try:
                JM_ACCOUNT_PATH.unlink()
            except FileNotFoundError:
                pass
            await self.api.qq.post_private_msg(user_id, text="已清除保存的 JM 账号密码")
            return

    # ------------------------------------------------------------------
    # 业务逻辑
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_album_ids(text: str) -> list[str]:
        """从消息中解析全部本子 id。

        支持的写法（可跨行、大小写不敏感）：
        - ``/jm 350234 350235``（一个指令多个车号）
        - ``/jm 350234 /jm 350235``（一条消息多个指令）
        - ``/jm350234``（无空格也可识别）
        - ``/jm 350234极品``（数字后紧跟中文等字符，只取数字前缀）

        每个 ``/jm`` 之后逐 token 读取开头的连续数字，遇到第一个不以
        数字开头的 token 即停止（``/jm help`` 等不会被当成车号）。
        结果去重并保序。
        """
        album_ids: list[str] = []
        # jm 必须位于行首或空白之后（斜杠可有可无），且后面是空白/数字/结尾，
        # 避免误匹配 x/jm 5、jmusic 这类文本
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

    async def _download_albums(
        self,
        album_ids: list[str],
        *,
        send_msg,
        upload_file,
        encrypt: bool,
    ) -> None:
        """批量下载本子：逐个下载、生成 PDF 并随下随发，最后汇总结果。

        :param send_msg: 异步回调，签名 send_msg(text: str)
        :param upload_file: 异步回调，签名 upload_file(file, name)
        :param encrypt: 是否对 PDF 加密（群聊开启、私聊关闭）
        """
        total = len(album_ids)
        id_preview = "、".join(album_ids)
        await send_msg(f"开始下载 {total} 个本子：{id_preview}，请稍候……")

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []

        for album_id in album_ids:
            try:
                file_path = await self._fetch_pdf(album_id)
                if encrypt:
                    file_path = await self._encrypt_pdf(album_id, file_path)
                await upload_file(file=file_path, name=f"{album_id}.pdf")
                succeeded.append(album_id)
            except Exception as e:
                LOG.exception("下载本子 %s 失败", album_id)
                failed.append((album_id, self._format_download_error(album_id, e)))

        # 单个车号：保持旧行为，失败才提示，成功不打扰
        if total == 1:
            if failed:
                await send_msg(failed[0][1])
            return

        # 多个车号：发送一条汇总
        lines = [f"批量下载完成：成功 {len(succeeded)} 个，失败 {len(failed)} 个"]
        for album_id, reason in failed:
            lines.append(f"{album_id}：{reason}")
        await send_msg("\n".join(lines))

    @staticmethod
    def _format_download_error(album_id: str, e: Exception) -> str:
        """把下载阶段的异常转换为发给用户的友好提示。"""
        if isinstance(e, MissingAlbumPhotoException):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        # 下载未产出 PDF（jmcomic 重试耗尽、本子不可见等场景），同样提示本子不存在
        if isinstance(e, FileNotFoundError) and "未找到生成的 PDF" in str(e):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        return f"下载/发送失败：{e}"

    async def _fetch_pdf(self, album_id: str) -> str:
        """下载相册并生成 PDF，返回 PDF 绝对路径。"""
        # 已保存账号但当前未登录（如启动时登录失败/cookies 过期），先补登录
        await self._ensure_jm_login()

        def _download() -> None:
            # jmcomic 接收 album id 列表
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
        candidates = [BOT_DIR]
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

    def _apply_download_root(self, new_path: str) -> str:
        """运行时修改下载路径：保存配置、重建三个文件夹与 jm 配置、后台迁移旧文件。"""
        old_root = self.download_root
        target = Path(new_path)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return f"下载路径设置失败，无法创建目录：{e}"

        self._download_root = target
        self._plugin_config["download_root"] = str(target)
        self._save_plugin_config()
        # 重建 jmcomic 配置（图片/PDF 输出指向新路径下的 stock/pdf）
        self._prepare_jm_option()

        task = asyncio.create_task(
            asyncio.to_thread(self._migrate_old_downloads, [old_root])
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        LOG.info("JMBot 下载路径已切换: %s -> %s", old_root, target)
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
                        LOG.warning("迁移 %s 失败: %s", item, e)
                # 旧目录清空后删除；非空（有迁移失败的残留）则保留，下轮再处理
                try:
                    old_dir.rmdir()
                except OSError:
                    pass
                if moved:
                    LOG.info("已将 %d 项旧下载内容迁移到 %s", moved, new_dir)

    async def _cleanup_loop(self) -> None:
        """启动时先清理一次，之后每隔 CLEANUP_INTERVAL_SECONDS 清理一次。"""
        # 首次清理前等待旧目录迁移完成（最多 30 分钟），
        # 使迁移过来的过期文件也能在本轮被清理
        migration = self._migration_task
        if migration is not None:
            try:
                await asyncio.wait_for(asyncio.shield(migration), timeout=1800)
            except asyncio.TimeoutError:
                LOG.warning("旧目录迁移耗时过长，首次清理不再等待")
            except Exception:
                pass

        while True:
            try:
                removed = await asyncio.to_thread(self._cleanup_old_files)
                if removed:
                    LOG.info(
                        "自动清理：已删除 %d 个超过 %d 天的下载文件",
                        removed,
                        CLEANUP_KEEP_SECONDS // (24 * 60 * 60),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                LOG.warning("自动清理失败: %s", e)
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    def _cleanup_old_files(self) -> int:
        """删除下载路径下 stock/pdf/encrypt_pdf 中超过 3 天的文件及空目录。

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
