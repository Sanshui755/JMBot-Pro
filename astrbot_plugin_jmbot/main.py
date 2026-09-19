"""
JMBot —— AstrBot 版禁漫下载插件

群聊 / 私聊发送 ``/jm <id>``，机器人自动下载相册、生成 PDF 并发送文件。
支持批量：``/jm 350234 350235`` 或一条消息内多条 ``/jm`` 指令，
数字后紧跟中文备注（如 ``/jm 350234极品``）也能正确识别。
发送 ``/jmv <任意含车号的文本>`` 只查询本子详情（标题/作者/标签/页数等），
不下载任何图片，支持直接粘贴链接或整段文本，自动从中提取车号。
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
import threading
import time
from pathlib import Path

import jmcomic
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import File
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from jmcomic.jm_exception import MissingAlbumPhotoException
from jmcomic.jm_plugin import JmOptionPlugin

from .set_password import set_password_pdf

PLUGIN_DIR = Path(__file__).resolve().parent
JM_CONFIG_TEMPLATE = PLUGIN_DIR / "config.yml"

HELP_TEXT = (
    "使用方法：\n输入 /jm+空格+id ，机器人会自动下载生成 pdf 并发送消息。\n"
    "例： /jm 350234\n"
    "支持批量： /jm 350234 350235（或一条消息里发多条 /jm 指令）\n"
    "数字后加中文备注也可以，如 /jm 350234极品\n"
    "超分辨率下载（画质提升）：\n"
    "  /jm -h 350234 用插件配置页选择的默认模型（默认 Real-ESRGAN）\n"
    "  /jm -hr 350234 强制用 Real-ESRGAN，/jm -hw 350234 强制用 waifu2x\n"
    "  ⚠ 超分需逐张放大图片，耗时比普通下载明显增加（无独显时更慢），\n"
    "    请耐心等待、勿重复发指令；首次使用会自动下载工具包\n"
    "    （Real-ESRGAN 约45MB/waifu2x 约35MB，仅一次），PDF 体积也会变大\n"
    "站内搜索：/jms <关键词>（如 /jms 全彩 人妻），结果回复 1 翻页/0 退出\n"
    "按作者搜索：/jma <作者名>（如 /jma AREA188），结果回复 1 翻页/0 退出\n"
    "只看详情不下载：/jmv 350234（可直接粘贴含车号的链接或整段文本）\n"
    "下载的文件仅在本机保留3天，到期自动删除\n"
    "如有pdf有密码,默认密码为114514"
)

JMV_HELP_TEXT = (
    "本子详情查询（只看不下载）：\n"
    "输入 /jmv+空格+任意含车号的内容，机器人会自动提取其中的数字。\n"
    "例： /jmv 350234\n"
    "也可直接粘贴链接或整段文本，如：/jmv https://18comic.vip/album/350234/\n"
    "需要下载请发送 /jm 350234"
)

JMS_HELP_TEXT = (
    "站内搜索：/jms <关键词>\n"
    "例：/jms 全彩 人妻\n"
    "支持无空格写法：/jms全彩\n"
    "每页显示 10 条：回复 1 查看下 10 条，回复 0 退出（5 分钟内仅你本人操作有效）\n"
    "需要下载请发送 /jm <id>"
)

JMA_HELP_TEXT = (
    "按作者搜索：/jma <作者名>\n"
    "例：/jma AREA188\n"
    "支持无空格写法：/jmaAREA188\n"
    "每页显示 10 条：回复 1 查看下 10 条，回复 0 退出（5 分钟内仅你本人操作有效）\n"
    "需要下载请发送 /jm <id>"
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

# ---------------- 搜索 ----------------
SEARCH_RESULTS_PER_PAGE = 10
# 搜索翻页会话有效期（秒）：发起搜索后 5 分钟内回复 1/0 有效
SEARCH_SESSION_TTL = 300
# 私聊跳过正则：覆盖 jm/jmv/jms/jma 所有形态
# v 后必须跟 空格/数字/结尾（不匹配 /jmversion）
# s/a 后跟任意非空字符（关键词可任意开头）
# 纯 jm 后必须跟 空格/数字/结尾
SKIP_JM_PATTERN = r"/?jm(?:v(?=\s|\d|$)|[sa]|(?=\s|\d|$))"

# ---------------- 超分辨率（ncnn-vulkan 外部二进制，无需 torch）----------------
# /jm -h 与 /jm -hr 默认走 Real-ESRGAN；/jm -hw 走 waifu2x。
# 两套工具都是 ncnn-vulkan 预编译二进制，首次使用时按所选工具自动下载。
# 注意两者命令行语义不同：
#   Real-ESRGAN: -n <模型名> -s <放大倍数>
#   waifu2x:      -n <降噪级别 0-3> -s <放大倍数>（模型由内置 models-cunet 提供）
SUPERRES_FORMAT = "jpg"
# 单张超分 subprocess 超时（秒）：waifu2x 在中端独显上约 20-30s/张，留足余量。
# 逐张调用下单张卡死/崩溃只损失该张（回退原图），不再像整章超时那样损失全章。
SUPERRES_PER_IMAGE_TIMEOUT = 240

# PDF 文件发送：NapCat 偶发 retcode=1200 "rich media transfer failed"
# （QQ 风控/富媒体缓存瞬时故障），重试往往即可成功。
PDF_SEND_RETRIES = 3
PDF_SEND_RETRY_DELAY = 3.0

SUPERRES_TOOLS = {
    "realesrgan": {
        "dir": "realesrgan",
        "exe": "realesrgan-ncnn-vulkan.exe",
        "zip_url": (
            "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
            "realesrgan-ncnn-vulkan-20220424-windows.zip"
        ),
        "zip_name": "realesrgan-ncnn-vulkan.zip",
        "label": "Real-ESRGAN",
        "download_mb": "约 45MB",
        "args": ["-n", "realesrgan-x4plus-anime", "-s", "4"],
    },
    "waifu2x": {
        "dir": "waifu2x",
        "exe": "waifu2x-ncnn-vulkan.exe",
        "zip_url": (
            "https://github.com/nihui/waifu2x-ncnn-vulkan/releases/download/"
            "20250915/waifu2x-ncnn-vulkan-20250915-windows.zip"
        ),
        "zip_name": "waifu2x-ncnn-vulkan.zip",
        "label": "waifu2x",
        "download_mb": "约 35MB",
        # -n 2 = 降噪级别 2（适合动漫），-s 2 = 2x 放大（waifu2x 最佳质量倍率）
        "args": ["-n", "2", "-s", "2"],
    },
}


# ---------------- 下载进度日志（jmcomic 生命周期插件）----------------
# jmcomic 下载器在 before_photo/after_image/after_photo/after_album 等生命周期点，
# 按注册表构建插件实例并调用 invoke()，事件类型由挂载的分组决定（每次全新实例，
# 实例属性无法跨事件累计），因此计数状态统一放在模块级字典，按章节 photo_id 维护。
# 日志走 AstrBot logger（WebUI 日志页/控制台可见），不发送 QQ 消息。
_DL_PROGRESS_LOCK = threading.Lock()
_DL_PROGRESS_STATE: dict[str, dict] = {}  # photo_id -> {album_id, total, done}


def _jm_display_id(entity_id) -> str:
    s = str(entity_id)
    return s if s.upper().startswith("JM") else f"JM{s}"


class _JMBotProgBeforeAlbum(JmOptionPlugin):
    plugin_key = "jmbot_prog_before_album"

    def invoke(self, album=None, **_):
        if album is None:
            return
        # 专辑详情一到手立即登记标题与章节数：
        # 总张数要等各章节详情拉取完（before_photo）才可知，此阶段进度页先显示「准备中」
        title = (getattr(album, "title", "") or getattr(album, "name", "") or "").strip()
        _task_album_meta(str(album.id), title=title, chapters_total=len(album))


class _JMBotProgBeforePhoto(JmOptionPlugin):
    plugin_key = "jmbot_prog_before_photo"

    def invoke(self, photo=None, **_):
        if photo is None:
            return
        with _DL_PROGRESS_LOCK:
            _DL_PROGRESS_STATE[str(photo.id)] = {
                "album_id": str(photo.from_album.id),
                "total": len(photo),
                "done": 0,
            }
        logger.info(
            f"下载开始：本子-{_jm_display_id(photo.from_album.id)} "
            f"章节-{_jm_display_id(photo.id)}，共 {len(photo)} 张"
        )
        _task_chapter_begin(str(photo.from_album.id), str(photo.id), len(photo))


class _JMBotProgAfterImage(JmOptionPlugin):
    plugin_key = "jmbot_prog_after_image"

    def invoke(self, image=None, **_):
        if image is None:
            return
        photo_id = str(image.from_photo.id)
        with _DL_PROGRESS_LOCK:
            state = _DL_PROGRESS_STATE.get(photo_id)
            if state is None:
                return
            state["done"] += 1
            done, total, album_id = state["done"], state["total"], state["album_id"]
        logger.info(
            f"下载进度：本子-{_jm_display_id(album_id)} "
            f"章节-{_jm_display_id(photo_id)} {done}/{total}（{image.filename}）"
        )
        _task_image_done(album_id, photo_id)


class _JMBotProgAfterPhoto(JmOptionPlugin):
    plugin_key = "jmbot_prog_after_photo"

    def invoke(self, photo=None, **_):
        if photo is None:
            return
        photo_id = str(photo.id)
        with _DL_PROGRESS_LOCK:
            state = _DL_PROGRESS_STATE.pop(photo_id, None)
        if state is None:
            return
        done, total = state["done"], state["total"]
        mark = "完成" if done >= total else "结束（部分图片失败）"
        logger.info(
            f"下载{mark}：本子-{_jm_display_id(state['album_id'])} "
            f"章节-{_jm_display_id(photo_id)}，图片 {done}/{total}"
        )


class _JMBotProgAfterAlbum(JmOptionPlugin):
    plugin_key = "jmbot_prog_after_album"

    def invoke(self, album=None, **_):
        if album is None:
            return
        logger.info(f"下载完成：本子-{_jm_display_id(album.id)}（共 {len(album)} 章）")
        title = (getattr(album, "title", "") or "").strip()
        if title:
            _task_update_by_album(str(album.id), title=title)


def _register_jm_progress_plugins() -> None:
    """把进度日志插件注册进 jmcomic 注册表（按 plugin_key 覆盖，幂等）。"""
    for cls in (
        _JMBotProgBeforeAlbum,
        _JMBotProgBeforePhoto,
        _JMBotProgAfterImage,
        _JMBotProgAfterPhoto,
        _JMBotProgAfterAlbum,
    ):
        jmcomic.JmModuleConfig.register_plugin(cls)


# ---------------- WebUI 实时进度（任务注册表）----------------
# 每个车号的下载 = 一个任务。命令入口创建登记，jmcomic 生命周期钩子 /
# 超分逐张循环 / PDF 渲染各阶段更新，经 register_web_api("progress") 暴露
# 只读端点，供插件进度页（pages/progress/，AstrBot 4.x 插件页面约定目录）每 1 秒轮询渲染。
# 钩子在工作线程触发，故统一用 threading.Lock 保护。
_WEBUI_TASKS: dict[str, dict] = {}             # task_id -> 任务状态
_WEBUI_TASKS_LOCK = threading.Lock()
_WEBUI_ALBUM_INDEX: dict[str, set[str]] = {}   # album_id -> 引用该专辑的活跃 task_id
_WEBUI_DONE_TTL_SECONDS = 60                   # 已完成任务在主列表的保留秒数（到期自动移出）
_WEBUI_TASK_MAX = 50                           # 注册表上限（超出淘汰最旧已完成项）
_WEBUI_HISTORY_MAX = 100                       # 历史记录条数上限（超出淘汰最旧）
_WEBUI_HISTORY: list[dict] = []                # 已完成任务历史（含失败，新在前）


def _task_remove_locked(task_id: str) -> None:
    """删除任务并解除专辑索引（调用方须已持有 _WEBUI_TASKS_LOCK）。"""
    t = _WEBUI_TASKS.pop(task_id, None)
    if t is None:
        return
    ids = _WEBUI_ALBUM_INDEX.get(t["album_id"])
    if ids is not None:
        ids.discard(task_id)
        if not ids:
            _WEBUI_ALBUM_INDEX.pop(t["album_id"], None)


def _task_prune_locked(now: float) -> None:
    """清理过期/超额的已完成任务（调用方须已持有 _WEBUI_TASKS_LOCK）。"""
    stale = [
        tid
        for tid, t in _WEBUI_TASKS.items()
        if t["finished_at"] is not None
        and now - t["finished_at"] > _WEBUI_DONE_TTL_SECONDS
    ]
    for tid in stale:
        _task_remove_locked(tid)
    finished = sorted(
        (tid for tid, t in _WEBUI_TASKS.items() if t["finished_at"] is not None),
        key=lambda tid: _WEBUI_TASKS[tid]["finished_at"],
    )
    while len(_WEBUI_TASKS) > _WEBUI_TASK_MAX and finished:
        _task_remove_locked(finished.pop(0))


def _task_begin(album_id: str, user: str, flags: str, queued: bool = False) -> str:
    """登记新任务，返回 task_id。

    queued=True 时登记为「排队中」占位（批量下载入口预登记全部车号），
    实际开始下载时由 _task_mark_running 激活。
    """
    task_id = f"{album_id}-{int(time.time() * 1000)}"
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        _task_prune_locked(now)
        _WEBUI_TASKS[task_id] = {
            "task_id": task_id,
            "album_id": album_id,
            "title": "",
            "user": user,
            "flags": flags,
            "phase": "queued" if queued else "downloading",
            "done_imgs": 0,
            "total_imgs": 0,
            "chapters": [],
            "chapters_total": 0,
            "sr_done": 0,
            "sr_total": 0,
            "sr_failed": 0,
            "sr_model": "",
            "pdf_size_mb": 0.0,
            "message": "",
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
        }
        _WEBUI_ALBUM_INDEX.setdefault(album_id, set()).add(task_id)
    return task_id


def _task_mark_running(task_id: str) -> None:
    """排队任务真正开始下载：phase→downloading，started_at 重置为当前时刻。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        t = _WEBUI_TASKS.get(task_id)
        if t is not None and t["finished_at"] is None:
            t["phase"] = "downloading"
            t["started_at"] = now
            t["updated_at"] = now


def _task_update(task_id: str, **fields) -> None:
    """按 task_id 更新任务字段。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        t = _WEBUI_TASKS.get(task_id)
        if t is not None:
            t.update(fields)
            t["updated_at"] = now


def _task_finish(task_id: str, phase: str, **fields) -> None:
    """任务收尾：写终态并从活跃索引移除。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        t = _WEBUI_TASKS.get(task_id)
        if t is None:
            return
        t.update(fields)
        t["phase"] = phase
        t["updated_at"] = now
        t["finished_at"] = now
        ids = _WEBUI_ALBUM_INDEX.get(t["album_id"])
        if ids is not None:
            ids.discard(task_id)
            if not ids:
                _WEBUI_ALBUM_INDEX.pop(t["album_id"], None)
        # 归档到历史（快照拷贝，主列表后续清理不影响）
        snap = dict(t)
        snap["chapters"] = [dict(c) for c in t["chapters"]]
        _WEBUI_HISTORY.insert(0, snap)
        del _WEBUI_HISTORY[_WEBUI_HISTORY_MAX:]


def _task_dismiss(task_id: str) -> None:
    """任务完成且 PDF 已成功发送：立即移出主列表（历史记录仍保留）。"""
    with _WEBUI_TASKS_LOCK:
        _task_remove_locked(task_id)


def _task_update_by_album(album_id: str, **fields) -> None:
    """按专辑号更新其全部活跃任务（下载钩子只知道专辑/章节）。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        for tid in _WEBUI_ALBUM_INDEX.get(album_id, ()):
            t = _WEBUI_TASKS.get(tid)
            if t is not None:
                t.update(fields)
                t["updated_at"] = now


def _task_chapter_begin(album_id: str, chapter_id: str, total: int) -> None:
    """下载开始新章节：累计总张数并登记章节明细。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        for tid in _WEBUI_ALBUM_INDEX.get(album_id, ()):
            t = _WEBUI_TASKS.get(tid)
            if t is not None:
                t["total_imgs"] += total
                t["chapters"].append({"id": chapter_id, "total": total, "done": 0})
                t["updated_at"] = now


def _task_album_meta(album_id: str, title: str, chapters_total: int) -> None:
    """专辑详情已获取：提前写入标题与预期章节数（总张数仍按章节逐步累计）。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        for tid in _WEBUI_ALBUM_INDEX.get(album_id, ()):
            t = _WEBUI_TASKS.get(tid)
            if t is not None:
                if title and not t["title"]:
                    t["title"] = title
                t["chapters_total"] = chapters_total
                t["updated_at"] = now


def _task_image_done(album_id: str, chapter_id: str) -> None:
    """下载完成单张：累计全局与章节计数。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        for tid in _WEBUI_ALBUM_INDEX.get(album_id, ()):
            t = _WEBUI_TASKS.get(tid)
            if t is not None:
                t["done_imgs"] += 1
                for ch in t["chapters"]:
                    if ch["id"] == chapter_id:
                        ch["done"] += 1
                        break
                t["updated_at"] = now


def _task_sr_bump(task_id: str, done: int = 0, failed: int = 0) -> None:
    """超分逐张计数（含断点续跑复用的张数）。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        t = _WEBUI_TASKS.get(task_id)
        if t is not None:
            t["sr_done"] += done
            t["sr_failed"] += failed
            t["updated_at"] = now


def _webui_tasks_snapshot() -> dict:
    """组装进度页数据：下载中在前、排队次之、已完成最后；另附历史记录。"""
    now = time.time()
    with _WEBUI_TASKS_LOCK:
        _task_prune_locked(now)
        active, finished = [], []
        for t in _WEBUI_TASKS.values():
            # 浅拷贝逐层展开，避免序列化期间被工作线程修改
            snap = dict(t)
            snap["chapters"] = [dict(c) for c in t["chapters"]]
            (finished if t["finished_at"] is not None else active).append(snap)
        # 下载中的任务排前，排队中的按登记时间倒序跟在后面
        active.sort(key=lambda t: (t["phase"] != "queued", -t["updated_at"]))
        finished.sort(key=lambda t: t["finished_at"], reverse=True)
        return {
            "tasks": active + finished,
            "history": list(_WEBUI_HISTORY),
            "server_time": time.time(),
        }


@register("astrbot_plugin_jmbot", "Sanshui755", "禁漫下载插件，批量下载/搜索翻页/双模型超分辨率/路径可配/自动清理", "2.3.3", "")
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

        # 超分辨率二进制路径（realesrgan / waifu2x 各自独立目录）
        self.superres_dirs: dict[str, Path] = {}
        self.superres_exes: dict[str, Path] = {}
        for _model, _cfg in SUPERRES_TOOLS.items():
            _dir = self.data_dir / _cfg["dir"]
            self.superres_dirs[_model] = _dir
            self.superres_exes[_model] = _dir / _cfg["exe"]
        # 超分辨率下载互斥锁（保护 img2pdf 插件临时禁用/恢复）
        self._super_res_lock = asyncio.Lock()
        # 下载互斥锁：序列化下载避免 JM 限流与插件状态竞争，
        # 但与 _super_res_lock 相互独立，故下一本的下载可与上一本的超分并行
        self._download_lock = asyncio.Lock()
        # 搜索翻页会话：key=(会话ID, 用户QQ) → 会话数据
        # 群聊中每位用户各自独立，只有发起人回复 1/0 才会命中自己的会话
        self._search_sessions: dict[tuple[str, str], dict] = {}

        # 后台把历史下载目录（旧版本布局）迁到当前路径
        self._migration_task = asyncio.create_task(
            asyncio.to_thread(self._migrate_old_downloads)
        )
        self._background_tasks.add(self._migration_task)
        self._migration_task.add_done_callback(self._background_tasks.discard)

        # WebUI 进度页数据端点（插件页面经 bridge apiGet("progress") 调用，
        # 实际路由 /api/v1/plugins/extensions/astrbot_plugin_jmbot/progress。
        # 注意：extensions 路由按「插件名 + 注册路由」整段匹配子路径，
        # 前端固定附加 {插件名}/ 前缀，故注册路由必须带同名前缀。）
        try:
            self.context.register_web_api(
                "astrbot_plugin_jmbot/progress",
                self._api_task_progress,
                ["GET"],
                "JMBot 下载/超分进度",
            )
        except Exception as e:  # 框架接口异常不应阻断插件加载
            logger.warning(f"注册 WebUI 进度端点失败: {e}")

        self._prepare_jm_option()
        self._load_jm_account()

        if not self.super_user:
            logger.warning("未配置超管 QQ，请在 AstrBot 管理面板的 JMBot 插件配置中填写")

        # 已保存 JM 账号则后台自动登录；不阻塞插件加载。
        # WebUI 配置页保存后会热重载插件，重载即触发这里的自动登录——
        # 相当于每次保存配置都做一次登录测试，结果见下方日志（成功/失败均打印）。
        if self.jm_username and self.jm_password:
            logger.info(
                f"检测到已配置 JM 账号({self.jm_cred_source})，开始后台自动登录测试"
            )
            task = asyncio.create_task(self._jm_login())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        else:
            logger.warning(
                "尚未配置 JM 账号：请在 WebUI 插件配置页填写 JM 账号/密码并保存，"
                "保存后插件会自动重载并尝试登录（结果见日志）；也可由超管私聊机器人发送 "
                "设置JM账号 / 设置JM密码"
            )

        # 启动下载产物自动清理任务（先清理一次，之后每隔 6 小时清理）
        cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._background_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._background_tasks.discard)

        logger.info("JMBot v2.3.3 已加载（指令消息已隔离：屏蔽默认 LLM 与陪伴/记忆插件）")
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

    @property
    def default_superres_model(self) -> str:
        """配置页选择的默认超分模型，仅允许 SUPERRES_TOOLS 中已有的键。"""
        value = str(self.config.get("superres_model", "realesrgan")).strip().lower()
        return value if value in SUPERRES_TOOLS else "realesrgan"

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
        # 挂载下载进度日志插件（输出到 AstrBot 日志，不影响 QQ 消息）
        _register_jm_progress_plugins()
        for _group, _key in (
            ("before_album", _JMBotProgBeforeAlbum.plugin_key),
            ("before_photo", _JMBotProgBeforePhoto.plugin_key),
            ("after_image", _JMBotProgAfterImage.plugin_key),
            ("after_photo", _JMBotProgAfterPhoto.plugin_key),
            ("after_album", _JMBotProgAfterAlbum.plugin_key),
        ):
            _plist = self.jm_option.plugins.src_dict.setdefault(_group, [])
            if not any(
                isinstance(_p, dict) and _p.get("plugin") == _key for _p in _plist
            ):
                _plist.append({"plugin": _key})
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
    def _detect_super_res(text: str) -> tuple[str | None, str]:
        """从命令文本检测超分辨率标志。

        - ``/jm -hw <id>`` → ("waifu2x", 去掉标志后的文本)
        - ``/jm -hr <id>`` → ("realesrgan", 去掉标志后的文本)
        - ``/jm -h <id>``  → ("default", 去掉标志后的文本)，
          具体模型由插件配置页 superres_model 决定
        - 无标志 → (None, 原文)

        注意三个分支必须按 -hw / -hr / -h 顺序判断，``-h`` 的正则
        不允许后跟字母，所以 -hr、-hw 都不会被误判为 default。
        """
        if re.search(r"(?:^|\s)-hw(?:\s|$)", text, re.IGNORECASE):
            model = "waifu2x"
        elif re.search(r"(?:^|\s)-hr(?:\s|$)", text, re.IGNORECASE):
            model = "realesrgan"
        elif re.search(r"(?:^|\s)-h(?:\s|$)", text, re.IGNORECASE):
            model = "default"
        else:
            return None, text
        clean = re.sub(r"(?:^|\s)-h(?:r|w)?(?=\s|$)", "", text, flags=re.IGNORECASE)
        return model, clean

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

        # 检测超分辨率标志：-h → 配置页默认模型，-hr → realesrgan，-hw → waifu2x
        raw_text = event.message_str or ""
        super_model, clean_text = self._detect_super_res(raw_text)
        if super_model == "default":
            super_model = self.default_superres_model

        # 从消息原文解析全部车号（/jm a b、多条 /jm、数字后带中文备注均支持）
        album_ids = self._parse_album_ids(clean_text)
        if not album_ids:
            yield event.plain_result(HELP_TEXT)
            return

        total = len(album_ids)
        id_preview = "、".join(album_ids)
        if super_model:
            mode_label = SUPERRES_TOOLS[super_model]["label"]
            mode_hint = (
                f"（{mode_label} 超分辨率模式：图片需逐张放大，"
                f"耗时比普通下载明显增加，请耐心等待）"
            )
        else:
            mode_hint = ""
        yield event.plain_result(f"开始下载 {total} 个本子{mode_hint}：{id_preview}，请稍候……")

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []

        # 预登记全部车号为「排队中」：进度页一次性展示整批，
        # 随循环逐个激活为下载中（失败的任务在流水线内落终态）
        queued_tasks = [
            (aid, _task_begin(aid, user_id, super_model or "", queued=True))
            for aid in album_ids
        ]

        async for aid, task_id, pdf_path, notice, error in \
                self._run_download_pipeline(album_ids, super_model, queued_tasks):
            if error:
                failed.append((aid, self._format_download_error(aid, error)))
                continue
            try:
                # 群聊按配置加密；私聊不加密
                if is_group and self.pdf_encrypt:
                    pdf_path = await self._encrypt_pdf(aid, pdf_path)
                # 直发+重试：框架 yield 发送的失败异常插件捕获不到（见方法注释）
                sent = await self._send_pdf_with_retry(event, pdf_path, aid)
            except Exception as e:  # 加密等本地处理失败
                logger.exception(f"/jm 发送本子 {aid} 失败: {e}")
                _task_finish(task_id, "failed", error=f"发送失败: {e}")
                failed.append((aid, self._format_download_error(aid, e)))
                continue
            if sent:
                if notice:
                    yield event.plain_result(notice)
                # PDF 已发出：立即移出主列表，记录归档到历史
                _task_dismiss(task_id)
                succeeded.append(aid)
            else:
                # 重试耗尽：明确告知用户 PDF 本地路径
                _task_finish(task_id, "failed", error="QQ 文件发送失败")
                failed.append(
                    (aid, f"PDF 已生成但 QQ 发送失败（已重试 {PDF_SEND_RETRIES} 次），"
                          f"文件已保留：{pdf_path}，可稍后重新发送 /jm {aid}")
                )

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

    # ------------------------------------------------------------------
    # /jmv 本子详情查询（不下载，群聊/私聊均可触发）
    # ------------------------------------------------------------------

    @filter.command("jmv", priority=500000)
    async def cmd_jmv(self, event: AstrMessageEvent):
        """查看本子详情：/jmv <任意含车号的文本>，自动提取数字，只查不下载。"""
        async for ret in self._jmv_impl(event, event.message_str or ""):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _jmv_impl(self, event: AstrMessageEvent, text: str):
        """本子详情查询流程，供标准指令与无空格兜底共用。"""
        # 与 /jm 相同的消息隔离策略
        self._claim(event)

        is_group = not event.is_private_chat()
        if is_group and not self.jm_on:
            # 群聊开关关闭：静默忽略，与 /jm 保持一致
            return

        album_id = self._extract_album_id(text)
        if not album_id:
            yield event.plain_result(JMV_HELP_TEXT)
            return

        yield event.plain_result(f"正在查询本子 {album_id} 的详情……")
        try:
            detail = await self._fetch_album_detail(album_id)
            yield event.plain_result(self._format_album_detail(detail))
        except Exception as e:
            logger.exception(f"/jmv 查询本子 {album_id} 详情失败: {e}")
            yield event.plain_result(self._format_view_error(album_id, e))

    # ------------------------------------------------------------------
    # /jms 站内搜索 & /jma 作者搜索（不下载，群聊/私聊均可触发）
    # ------------------------------------------------------------------

    @filter.command("jms", priority=500000)
    async def cmd_jms(self, event: AstrMessageEvent, keyword: str = ""):
        """站内搜索本子：/jms <关键词>"""
        async for ret in self._jms_impl(event, keyword):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    @filter.command("jma", priority=500000)
    async def cmd_jma(self, event: AstrMessageEvent, keyword: str = ""):
        """按作者搜索本子：/jma <作者名>"""
        async for ret in self._jma_impl(event, keyword):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _jms_impl(self, event: AstrMessageEvent, keyword: str):
        """站内搜索流程，供标准指令与无空格兜底共用。"""
        async for ret in self._run_search(event, keyword, "site"):
            yield ret

    async def _jma_impl(self, event: AstrMessageEvent, keyword: str):
        """按作者搜索流程，供标准指令与无空格兜底共用。"""
        async for ret in self._run_search(event, keyword, "author"):
            yield ret

    async def _run_search(self, event: AstrMessageEvent, keyword: str, search_type: str):
        """搜索主流程（/jms、/jma 共用），首页结果落地为翻页会话。"""
        self._claim(event)
        is_group = not event.is_private_chat()
        if is_group and not self.jm_on:
            return

        keyword = keyword.strip()
        if not keyword:
            yield event.plain_result(JMA_HELP_TEXT if search_type == "author" else JMS_HELP_TEXT)
            return

        searching = f"正在搜索作者「{keyword}」……" if search_type == "author" else f"正在搜索「{keyword}」……"
        yield event.plain_result(searching)
        try:
            page = await self._fetch_search_page(keyword, search_type=search_type, page=1)
        except Exception as e:
            logger.exception(f"搜索「{keyword}」失败: {e}")
            yield event.plain_result(f"搜索失败：{e}")
            return

        results = list(page.iter_id_title_tag())
        total = int(getattr(page, "total", 0) or 0)
        if not results:
            label = "作者" if search_type == "author" else "站内"
            yield event.plain_result(f"{label}搜索「{keyword}」无结果")
            return

        # 落地翻页会话（只有搜索发起人回复 1/0 才会命中）
        shown = min(SEARCH_RESULTS_PER_PAGE, len(results))
        self._search_sessions[self._search_session_key(event)] = {
            "query": keyword,
            "type": search_type,
            "buffer": results,
            "api_page": 1,
            "shown": shown,
            "total": total,
            "expire": time.time() + SEARCH_SESSION_TTL,
        }
        yield event.plain_result(
            self._format_search_batch(keyword, search_type, results[:shown], 0, shown, total)
        )

    def _search_session_key(self, event: AstrMessageEvent) -> tuple[str, str]:
        """翻页会话键：群聊=(群号, 用户QQ)，私聊=("pv", 用户QQ)。

        群内不同用户的键不同，天然保证只有搜索发起人能操作自己的会话。
        """
        user_id = str(event.get_sender_id())
        if event.is_private_chat():
            return ("pv", user_id)
        return (str(event.get_group_id() or ""), user_id)

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE,
        priority=500000,
    )
    async def on_search_page_control(self, event: AstrMessageEvent):
        """搜索翻页控制：有活跃搜索会话时，发起人回复 1 翻页 / 0 退出。"""
        async for ret in self._on_search_page_control_impl(event):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _on_search_page_control_impl(self, event: AstrMessageEvent):
        """仅在「发起人 + 5 分钟内 + 文本恰为 1/0」时接管消息，其余一律放行。"""
        text = (event.message_str or "").strip()
        if text not in ("0", "1"):
            return

        is_group = not event.is_private_chat()
        if is_group and not self.jm_on:
            return

        key = self._search_session_key(event)
        session = self._search_sessions.get(key)
        if session is None:
            # 该用户没有进行中的搜索（群里其他用户发的 1/0 也走这里）→ 放行
            return

        self._claim(event)

        if time.time() > session["expire"]:
            self._search_sessions.pop(key, None)
            yield event.plain_result(
                f"搜索会话已过期（超过 {SEARCH_SESSION_TTL // 60} 分钟），"
                f"请重新发送 /jms 或 /jma 搜索。"
            )
            return

        if text == "0":
            self._search_sessions.pop(key, None)
            yield event.plain_result("已退出搜索。")
            return

        # text == "1"：取下一批 10 条
        if session["shown"] >= session["total"]:
            yield event.plain_result("已经是最后一批结果了，回复 0 退出搜索。")
            return

        yield event.plain_result("正在翻页……")

        # 本地缓冲不足时再请求下一个 API 页追加到缓冲
        while session["shown"] >= len(session["buffer"]) and len(session["buffer"]) < session["total"]:
            next_api_page = session["api_page"] + 1
            try:
                p = await self._fetch_search_page(
                    session["query"], search_type=session["type"], page=next_api_page
                )
            except Exception as e:
                logger.exception(
                    f"搜索翻页失败「{session['query']}」page={next_api_page}: {e}"
                )
                yield event.plain_result(f"翻页失败：{e}")
                return
            new_items = list(p.iter_id_title_tag())
            if not new_items:
                break
            session["buffer"].extend(new_items)
            session["api_page"] = next_api_page

        start = session["shown"]
        end = min(start + SEARCH_RESULTS_PER_PAGE, len(session["buffer"]), session["total"])
        batch = session["buffer"][start:end]
        if not batch:
            # API 已无更多数据但 total 虚高，按实际结果收尾
            session["total"] = len(session["buffer"])
            yield event.plain_result("已经是最后一批结果了，回复 0 退出搜索。")
            return

        session["shown"] = end
        session["expire"] = time.time() + SEARCH_SESSION_TTL
        yield event.plain_result(
            self._format_search_batch(
                session["query"], session["type"], batch, start, end, session["total"]
            )
        )

    @filter.event_message_type(
        filter.EventMessageType.GROUP_MESSAGE | filter.EventMessageType.PRIVATE_MESSAGE,
        priority=500000,
    )
    async def on_jm_nospace(self, event: AstrMessageEvent):
        """兜底：识别无空格写法 ``/jm350234`` / ``/jmv350234``。"""
        async for ret in self._on_jm_nospace_impl(event):
            yield ret
        if event.get_extra("jmbot_claimed"):
            event.stop_event()

    async def _on_jm_nospace_impl(self, event: AstrMessageEvent):
        """兜底：识别无空格写法 ``/jm350234`` / ``/jmv350234`` / ``/jms关键词`` / ``/jma作者名``。

        标准指令过滤器只认 ``jm``/``jmv``/``jms``/``/jma`` 后接空格/结尾，
        无空格写法不会命中指令处理器，这里统一接住并解析。
        ``v`` 后必须紧跟数字才按详情查询处理，避免误吞 /jmversion。
        ``s``/``a`` 后紧跟任意非空字符即按搜索处理。
        """
        text = (event.message_str or "").strip()

        # /jmv350234：详情查询（v 后必须紧跟数字）
        if re.match(r"/?jmv(?=\d)", text, re.IGNORECASE):
            async for ret in self._jmv_impl(event, text):
                yield ret
            return

        # /jms关键词：站内搜索（s 后紧跟任意非空字符）
        if re.match(r"/?jms(?=\S)", text, re.IGNORECASE):
            keyword = re.sub(r"^/?jms\s*", "", text, count=1, flags=re.IGNORECASE).strip()
            async for ret in self._jms_impl(event, keyword):
                yield ret
            return

        # /jma作者名：作者搜索（a 后紧跟任意非空字符）
        if re.match(r"/?jma(?=\S)", text, re.IGNORECASE):
            keyword = re.sub(r"^/?jma\s*", "", text, count=1, flags=re.IGNORECASE).strip()
            async for ret in self._jma_impl(event, keyword):
                yield ret
            return

        # /jm350234：下载（检测 -h/-hr/-hw 超分辨率标志）
        # 先去掉超分标志再匹配数字模式
        raw_text = event.message_str or ""
        super_model, clean_text = self._detect_super_res(raw_text)
        if super_model == "default":
            super_model = self.default_superres_model
        clean_text = clean_text.strip()

        if not re.match(r"/?jm\d+", clean_text, re.IGNORECASE):
            return

        # 命中 jm 车号形态，同样禁止默认 LLM 响应
        self._claim(event)
        user_id = str(event.get_sender_id())

        album_ids = self._parse_album_ids(clean_text)
        if not album_ids:
            return

        is_group = not event.is_private_chat()
        if is_group and not self.jm_on:
            return

        total = len(album_ids)
        id_preview = "、".join(album_ids)
        if super_model:
            mode_label = SUPERRES_TOOLS[super_model]["label"]
            mode_hint = (
                f"（{mode_label} 超分辨率模式：图片需逐张放大，"
                f"耗时比普通下载明显增加，请耐心等待）"
            )
        else:
            mode_hint = ""
        yield event.plain_result(f"开始下载 {total} 个本子{mode_hint}：{id_preview}，请稍候……")

        succeeded: list[str] = []
        failed: list[tuple[str, str]] = []
        # 预登记全部车号为「排队中」（与 /jm 主入口一致）
        queued_tasks = [
            (aid, _task_begin(aid, user_id, super_model or "", queued=True))
            for aid in album_ids
        ]
        async for aid, task_id, pdf_path, notice, error in \
                self._run_download_pipeline(album_ids, super_model, queued_tasks):
            if error:
                failed.append((aid, self._format_download_error(aid, error)))
                continue
            try:
                if is_group and self.pdf_encrypt:
                    pdf_path = await self._encrypt_pdf(aid, pdf_path)
                # 直发+重试：框架 yield 发送的失败异常插件捕获不到（见方法注释）
                sent = await self._send_pdf_with_retry(event, pdf_path, aid)
            except Exception as e:  # 加密等本地处理失败
                logger.exception(f"/jm(无空格) 发送本子 {aid} 失败: {e}")
                _task_finish(task_id, "failed", error=f"发送失败: {e}")
                failed.append((aid, self._format_download_error(aid, e)))
                continue
            if sent:
                if notice:
                    yield event.plain_result(notice)
                # PDF 已发出：立即移出主列表，记录归档到历史
                _task_dismiss(task_id)
                succeeded.append(aid)
            else:
                # 重试耗尽：明确告知用户 PDF 本地路径
                _task_finish(task_id, "failed", error="QQ 文件发送失败")
                failed.append(
                    (aid, f"PDF 已生成但 QQ 发送失败（已重试 {PDF_SEND_RETRIES} 次），"
                          f"文件已保留：{pdf_path}，可稍后重新发送 /jm {aid}")
                )

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
        text = event.message_str or ""
        user_id = str(event.get_sender_id())
        logger.info(f"私聊消息: {text} (from {user_id})")

        # /jm、/jmv、/jms、/jma 指令交给指令处理器与无空格兜底处理器，这里不重复处理
        # （/jm 350234、/jm350234、/jmv 350234、/jmv350234、
        #   /jms 关键词、/jms关键词、/jma 作者、/jma作者 均跳过；
        # JM状态/JM帮助 等中文命令不受影响）
        if re.match(SKIP_JM_PATTERN, text, re.IGNORECASE):
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

        # 空消息（图片/表情/戳一戳/纯空白等非文本内容）不属于 JMBot 指令，
        # 直接放行，避免 "".splitlines()[0] 触发 IndexError
        if not text:
            return

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
    def _extract_album_id(text: str) -> str:
        """从任意文本中提取一个本子 id（``/jmv`` 专用）。

        去掉开头的 ``/jmv`` 指令后：
        1. 优先取 ``album``/``photo``/``jm`` 关键字附近的数字，
           兼容直接粘贴的站点链接（如 .../album/350234/）；
        2. 否则取文本中最长的连续数字（至少 4 位），一样长取第一个，
           尽量避开年份等短数字干扰。
        """
        body = re.sub(r"^/?jmv\s*", "", text.strip(), count=1, flags=re.IGNORECASE)
        context_match = re.search(
            r"(?:album|photo|jm)[^\d\n]{0,10}?(\d{4,})", body, re.IGNORECASE
        )
        if context_match:
            return context_match.group(1)
        candidates = re.findall(r"\d{4,}", body)
        if candidates:
            return max(candidates, key=len)
        return ""

    @staticmethod
    async def _send_pdf_with_retry(
        event: AstrMessageEvent, pdf_path: Path, album_id: str
    ) -> bool:
        """直发 PDF 文件并重试，返回是否成功。

        之前用 ``yield chain_result`` 把文件交给框架发送：NapCat 发送失败
        （retcode=1200 rich media transfer failed，多为 QQ 风控/富媒体缓存
        瞬时故障）的异常发生在框架 respond 阶段，插件内的 try/except
        捕获不到，用户侧表现为「已开始下载」之后再无任何回复。
        改为 ``event.send()`` 直发——失败会抛异常，可在插件内重试并
        明确告知用户最终结果。
        """
        chain = MessageChain(
            chain=[File(file=str(pdf_path), name=f"{album_id}.pdf")]
        )
        for attempt in range(1, PDF_SEND_RETRIES + 1):
            try:
                await event.send(chain)
                if attempt > 1:
                    logger.info(f"PDF 发送成功（第 {attempt} 次重试）: {album_id}")
                return True
            except Exception as e:  # noqa: BLE001 - 协议端异常类型多样
                logger.warning(
                    f"PDF 发送失败（第 {attempt}/{PDF_SEND_RETRIES} 次）"
                    f"{album_id}: {e}"
                )
                if attempt < PDF_SEND_RETRIES:
                    await asyncio.sleep(PDF_SEND_RETRY_DELAY)
        return False

    @staticmethod
    def _format_download_error(album_id: str, e: Exception) -> str:
        """把下载阶段的异常转换为发给用户的友好提示。"""
        if isinstance(e, MissingAlbumPhotoException):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        if isinstance(e, FileNotFoundError) and "未找到生成的 PDF" in str(e):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        return f"下载/发送失败：{e}"

    @staticmethod
    def _format_view_error(album_id: str, e: Exception) -> str:
        """把详情查询阶段的异常转换为发给用户的友好提示。"""
        if isinstance(e, MissingAlbumPhotoException):
            return ALBUM_NOT_FOUND_TEXT.format(album=album_id)
        return f"查询本子详情失败：{e}"

    async def _fetch_album_detail(self, album_id: str):
        """请求本子详情实体（只发一次详情请求，不下载任何图片）。

        优先使用网页端客户端（标签/作者/页数/日期更完整），失败则回退
        到移动端 API（标签偏少、无页数和日期，但至少能返回基本信息）。
        """
        await self._ensure_jm_login()

        async def _query_html():
            def _do():
                client = self.jm_option.new_jm_client(impl="html")
                return client.get_album_detail(album_id)
            return await asyncio.to_thread(_do)

        def _query_api():
            client = self.jm_option.build_jm_client()
            return client.get_album_detail(album_id)

        try:
            return await asyncio.wait_for(_query_html(), timeout=15)
        except asyncio.TimeoutError:
            logger.info(f"/jmv HTML 客户端超时，回退到 API 客户端: {album_id}")
        except Exception as e:
            logger.info(f"/jmv HTML 客户端失败({e})，回退到 API 客户端: {album_id}")
        return await asyncio.to_thread(_query_api)

    async def _fetch_search_page(self, query: str, search_type: str = "site", page: int = 1):
        """调用 JM 搜索 API，返回 JmSearchPage。

        优先使用网页端客户端（标签更完整），20 秒超时后回退移动端 API。
        search_type: "site" → search_site, "author" → search_author
        page: API 页码（每页条数由 JM 端决定，本地再按 10 条切片展示）
        """
        await self._ensure_jm_login()

        def _search_html():
            client = self.jm_option.new_jm_client(impl="html")
            if search_type == "author":
                return client.search_author(query, page=page)
            return client.search_site(query, page=page)

        def _search_api():
            client = self.jm_option.build_jm_client()
            if search_type == "author":
                return client.search_author(query, page=page)
            return client.search_site(query, page=page)

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_search_html), timeout=20
            )
        except asyncio.TimeoutError:
            logger.info(f"搜索 HTML 客户端超时，回退到 API: {query}")
        except Exception as e:
            logger.info(f"搜索 HTML 客户端失败({e})，回退到 API: {query}")
        return await asyncio.to_thread(_search_api)

    @staticmethod
    def _format_search_batch(
        query: str,
        search_type: str,
        batch: list,
        start: int,
        shown: int,
        total: int,
    ) -> str:
        """渲染一批（10 条）搜索结果，start 为本批第一条在全局结果中的 0 基下标。

        尾部附带翻页操作提示：未到末尾提示回复 1/0，到末尾只提示 0。
        """
        search_label = "作者" if search_type == "author" else "站内"
        lines = [
            f"{search_label}搜索「{query}」的结果"
            f"（共 {total} 个，当前第 {start + 1}-{shown} 个）："
        ]
        for offset, (aid, title, tags) in enumerate(batch):
            title_short = (title or "(无标题)")[:40]
            lines.append(f"{start + offset + 1}. [{aid}] {title_short}")
            if tags:
                tag_list = [str(t) for t in tags[:5]]
                tag_text = "、".join(tag_list)
                if len(tag_text) > 30:
                    tag_text = tag_text[:30] + "…"
                lines.append(f"   标签：{tag_text}")

        if shown < total:
            lines.append(
                "—— 回复 1 查看下 10 条，回复 0 退出"
                f"（{SEARCH_SESSION_TTL // 60} 分钟内有效，仅你本人操作有效）"
            )
        else:
            lines.append("—— 已到最后一条，回复 0 退出搜索")
        lines.append("需要下载请发送：/jm <id>（超分辨率下载：/jm -h <id>）")
        return "\n".join(lines)

    @staticmethod
    def _format_album_detail(detail) -> str:
        """把 JmAlbumDetail 渲染成发给用户的纯文本详情。

        移动端 API 不返回页数/发布日期/更新日期（对应字段为 0 或
        ``'0'``），也不返回完整标签和作者。这些字段仅在有有效值时展示。
        作者为空时从标题方括号 ``[xxx]`` 中提取作为备选。
        """

        def join_list(items) -> str:
            cleaned = [str(x).strip() for x in (items or []) if str(x).strip()]
            return "、".join(cleaned) if cleaned else "无"

        tags = list(detail.tags or [])
        tag_text = join_list(tags)

        lines = [
            f"本子详情（车号 {detail.album_id}）",
            f"标题：{detail.name or '无'}",
        ]

        # 作者：优先取 API/HTML 返回；为空则从标题 [xxx] 方括号提取
        authors = join_list(detail.authors)
        if authors == "无":
            brackets = re.findall(r"\[([^\]]+)\]", detail.name or "")
            if brackets:
                authors = "、".join(brackets)
        if authors != "无":
            lines.append(f"作者：{authors}")

        actors = join_list(detail.actors)
        if actors != "无":
            lines.append(f"登场人物：{actors}")

        works = join_list(detail.works)
        if works != "无":
            lines.append(f"作品：{works}")

        lines.append(f"标签：{tag_text}")

        # 页数/章节：移动端 API 恒为 0，仅网页端能取到时才展示
        page_count = int(getattr(detail, "page_count", 0) or 0)
        if page_count > 0:
            episode_count = len(detail.episode_list)
            suffix = f"（共 {episode_count} 章）" if episode_count > 1 else ""
            lines.append(f"页数：{page_count} 页{suffix}")

        # 发布/更新日期：移动端 API 恒为 '0'，仅有效值才展示
        pub_date = str(getattr(detail, "pub_date", "") or "").strip()
        update_date = str(getattr(detail, "update_date", "") or "").strip()
        if pub_date and pub_date != "0":
            lines.append(f"发布：{pub_date}")
        if update_date and update_date != "0":
            lines.append(f"更新：{update_date}")

        lines.append(
            f"喜欢：{detail.likes or 0} ｜ 观看：{detail.views or 0}"
            f" ｜ 评论：{detail.comment_count}"
        )

        description = str(getattr(detail, "description", "") or "").strip()
        if description:
            # 简介可能很长，截断防止消息过长
            if len(description) > 120:
                description = description[:120] + "…"
            lines.append(f"简介：{description}")

        lines.append(f"链接：https://18comic.vip/album/{detail.album_id}/")
        lines.append(f"需要下载请发送：/jm {detail.album_id}")
        return "\n".join(lines)

    async def _api_task_progress(self):
        """WebUI 进度页数据源（只读）。"""
        return {"status": "ok", "data": _webui_tasks_snapshot()}

    async def _download_album(
        self, album_id: str, super_model: str | None
    ) -> list[str]:
        """下载专辑原图（下载锁内，可与其他专辑的超分/PDF生成并行）。

        普通模式与超分模式统一禁用 img2pdf 插件，只下载原图，返回图片路径列表。
        PDF 生成（普通直接合并 / 超分后合并）由调用方在下载锁外完成，
        确保跨命令模式交替时 ``after_album`` 插件状态始终一致无竞争。
        """
        await self._ensure_jm_login()

        async with self._download_lock:
            original_after_album = self.jm_option.plugins.src_dict.get(
                "after_album", []
            )
            image_paths: list[str] = []
            try:
                # 所有模式统一禁用 img2pdf：下载阶段只产生原图，
                # PDF 合并交给后处理（_make_pdf / _super_res_and_pdf）在锁外做
                self.jm_option.plugins.src_dict["after_album"] = []

                def _download_raw():
                    return self.jm_option.download_album(album_id)

                result = await asyncio.to_thread(_download_raw)
                image_paths = list(result.manifest.image_filepath_list)
            finally:
                self.jm_option.plugins.src_dict["after_album"] = original_after_album

            if not image_paths:
                raise FileNotFoundError(f"下载完成但未找到图片文件: {album_id}")
            return image_paths

    async def _fetch_pdf_tracked(
        self,
        user_id: str,
        album_id: str,
        super_model: str | None,
        task_id: str | None = None,
    ) -> tuple[str, str | None]:
        """带 WebUI 进度跟踪的下载：登记任务 → 下载 → 写终态。

        task_id 传入命令入口预登记的排队任务（批量场景）；为 None 时在此登记。
        下载失败同样落终态（phase=failed）后再抛出，由调用方决定如何回复。
        """
        if task_id is None:
            task_id = _task_begin(album_id, user_id, super_model or "")
        else:
            _task_mark_running(task_id)
        try:
            pdf_path, notice = await self._fetch_pdf(
                album_id, super_model=super_model, task_id=task_id
            )
        except Exception as e:
            _task_finish(task_id, "failed", message=str(e)[:200])
            raise
        size_mb = 0.0
        try:
            size_mb = round(Path(pdf_path).stat().st_size / 1048576, 1)
        except OSError:
            pass
        _task_finish(task_id, "done", pdf_size_mb=size_mb, message=notice or "")
        return pdf_path, notice

    async def _run_download_pipeline(
        self,
        album_ids: list[str],
        super_model: str | None,
        queued_tasks: list[tuple[str, str]],
    ):
        """滑动流水线：下一本的下载与上一本的超分并行。

        yield (aid, task_id, pdf_path|None, notice|None, error|None)。
        - pdf_path 非 None：成功，调用方发送 PDF 后应 _task_dismiss
        - error 非 None：失败，调用方记录失败原因
        """
        if not queued_tasks:
            return

        # 启动第一个专辑的下载（后台 task，不阻塞后续循环）
        download_task = asyncio.create_task(
            self._download_album(album_ids[0], super_model)
        )

        for i, (aid, task_id) in enumerate(queued_tasks):
            _task_mark_running(task_id)
            # 等待当前专辑下载完成
            try:
                result = await download_task
            except Exception as e:
                logger.exception(f"/jm 下载本子 {aid} 失败: {e}")
                _task_finish(task_id, "failed", message=str(e)[:200])
                # 下载失败不影响后续：启动下一本下载
                if i + 1 < len(queued_tasks):
                    download_task = asyncio.create_task(
                        self._download_album(album_ids[i + 1], super_model)
                    )
                yield (aid, task_id, None, None, e)
                continue

            # 当前专辑下载完成 → 立即启动下一本下载（与当前超分并行）
            if i + 1 < len(queued_tasks):
                download_task = asyncio.create_task(
                    self._download_album(album_ids[i + 1], super_model)
                )

            # 处理当前专辑：PDF 生成在下载锁外，可与下一本下载并行
            try:
                image_paths = result
                if not super_model:
                    # 普通模式：直接手动合并 PDF（不占下载锁/超分锁）
                    pdf_path = await self._make_pdf(aid, image_paths)
                    notice = None
                else:
                    # 超分模式：二进制可用则超分，不可用回退普通 PDF
                    cfg = SUPERRES_TOOLS[super_model]
                    label = cfg["label"]
                    exe_path = await self._ensure_superres_binary(super_model)
                    if exe_path is None:
                        logger.warning(
                            f"{label} 二进制不可用，回退到普通 PDF"
                        )
                        pdf_path = await self._make_pdf(aid, image_paths)
                        notice = (
                            f"⚠ {label} 二进制不可用，"
                            "本次已回退普通下载（无超分）"
                        )
                    else:
                        pdf_path, notice = await self._super_res_and_pdf(
                            aid, super_model, image_paths, task_id
                        )

                size_mb = 0.0
                try:
                    size_mb = round(Path(pdf_path).stat().st_size / 1048576, 1)
                except OSError:
                    pass
                _task_finish(task_id, "done", pdf_size_mb=size_mb,
                             message=notice or "")
                yield (aid, task_id, pdf_path, notice, None)
            except Exception as e:
                logger.exception(f"/jm 处理本子 {aid} 失败: {e}")
                _task_finish(task_id, "failed", message=str(e)[:200])
                yield (aid, task_id, None, None, e)

    async def _fetch_pdf(
        self,
        album_id: str,
        super_model: str | None = None,
        task_id: str | None = None,
    ) -> tuple[str, str | None]:
        """下载相册并生成 PDF，返回 (PDF 绝对路径, 降级提示或 None)。

        单专辑顺序路径（非流水线）：下载原图 → 超分(可选) → PDF。
        批量场景由 _run_download_pipeline 直接调用 _download_album 与
        _super_res_and_pdf 实现下载/超分并行。
        """
        image_paths = await self._download_album(album_id, super_model)
        if not super_model:
            pdf_path = await self._make_pdf(album_id, image_paths)
            return pdf_path, None
        # 超分模式：先检查二进制是否可用
        cfg = SUPERRES_TOOLS[super_model]
        label = cfg["label"]
        exe_path = await self._ensure_superres_binary(super_model)
        if exe_path is None:
            logger.warning(f"{label} 二进制不可用，回退到普通 PDF")
            pdf_path = await self._make_pdf(album_id, image_paths)
            return (
                pdf_path,
                f"⚠ {label} 二进制不可用，本次已回退普通下载（无超分）",
            )
        return await self._super_res_and_pdf(
            album_id, super_model, image_paths, task_id
        )

    async def _super_res_and_pdf(
        self, album_id: str, model: str, image_paths: list[str],
        task_id: str | None = None,
    ) -> tuple[str, str | None]:
        """超分辨率处理 + PDF 生成（超分锁内，下载已由 _download_album 完成）。

        返回 (PDF 绝对路径, 降级提示或 None)。
        """
        cfg = SUPERRES_TOOLS[model]
        label = cfg["label"]
        exe_path = self.superres_exes[model]  # 调用方已确认二进制可用

        async with self._super_res_lock:
            if task_id:
                _task_update(
                    task_id,
                    phase="superres",
                    sr_model=model,
                    sr_total=len(image_paths),
                    sr_done=0,
                    sr_failed=0,
                )

            # Step 1: 运行超分工具（逐张处理）
            # 输出统一放到 stock/_hr_<模型>/ 下，保留 <本子>/<章节> 层级，
            # Real-ESRGAN 与 waifu2x 各自独立顶层文件夹，互不覆盖。
            # 逐张调用而非整章一次调用：单张崩溃/超时只损失该张（回退原图），
            # 已生成的输出直接复用，重跑即可断点续跑。
            stock_root = self.download_root / "stock"
            hr_model_root = stock_root / f"_hr_{model}"
            input_dirs = sorted(set(Path(p).parent for p in image_paths))
            hr_image_paths: list[str] = []
            degraded = 0  # 超分失败、回退原图的张数

            def _run_one(cmd: list[str]) -> None:
                import subprocess
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=SUPERRES_PER_IMAGE_TIMEOUT,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"returncode={proc.returncode}: "
                        f"{proc.stderr[:300] if proc.stderr else '无错误输出'}"
                    )

            for img_dir in input_dirs:
                try:
                    rel = img_dir.relative_to(stock_root)
                except ValueError:
                    rel = Path(img_dir.parent.name) / img_dir.name
                hr_dir = hr_model_root / rel
                hr_dir.mkdir(parents=True, exist_ok=True)

                chapter_images = sorted(
                    Path(p) for p in image_paths if Path(p).parent == img_dir
                )
                total_imgs = len(chapter_images)
                logger.info(
                    f"{label} 逐张处理: {img_dir} -> {hr_dir}"
                    f"（共 {total_imgs} 张，单张超时 "
                    f"{SUPERRES_PER_IMAGE_TIMEOUT}s）"
                )

                ok_map: dict[Path, Path] = {}
                for idx, img_path in enumerate(chapter_images, 1):
                    out_path = hr_dir / f"{img_path.stem}.{SUPERRES_FORMAT}"
                    if out_path.exists():
                        # 断点续跑：已有输出直接复用（含上次中断留下的成果）
                        ok_map[img_path] = out_path
                        if task_id:
                            _task_sr_bump(task_id, done=1)
                        continue
                    cmd = [
                        str(exe_path),
                        "-i", str(img_path),
                        "-o", str(out_path),
                        *cfg["args"],
                        "-f", SUPERRES_FORMAT,
                    ]
                    try:
                        await asyncio.to_thread(_run_one, cmd)
                        ok_map[img_path] = out_path
                        logger.info(
                            f"{label} 超分进度 {idx}/{total_imgs}"
                            f"（{idx * 100 // total_imgs}%）：{img_path.name}"
                        )
                        if task_id:
                            _task_sr_bump(task_id, done=1)
                    except Exception as e:
                        degraded += 1
                        logger.warning(
                            f"{label} 第 {idx}/{len(chapter_images)} 张超分失败，"
                            f"回退原图 {img_path.name}: {e}"
                        )
                        if task_id:
                            _task_sr_bump(task_id, failed=1)
                # 按原始页序组装：成功的用超分图，失败的该张回退原图
                hr_image_paths.extend(
                    str(ok_map.get(img_path, img_path))
                    for img_path in chapter_images
                )

            logger.info(
                f"{label} 超分完成 {album_id}: 成功 "
                f"{len(image_paths) - degraded} 张，回退原图 {degraded} 张"
            )

            if not hr_image_paths:
                raise FileNotFoundError(f"超分辨率处理未产生输出图片: {album_id}")

            # Step 2: 手动 img2pdf 生成 PDF
            if task_id:
                _task_update(task_id, phase="rendering")
            pdf_path = await self._make_pdf(album_id, hr_image_paths)
            if not Path(pdf_path).exists():
                raise FileNotFoundError(f"超分辨率 PDF 生成失败: {pdf_path}")

            notice = None
            if degraded:
                notice = (
                    f"⚠ {label} 超分有 {degraded}/{len(image_paths)} 张处理失败，"
                    "这些页已用原图补齐，PDF 画质未完全提升"
                )
            return str(pdf_path), notice

    async def _make_pdf(self, album_id: str, image_paths: list[str]) -> str:
        """手动 img2pdf 合并图片为 PDF（不占用下载锁/超分锁）。

        普通下载与超分下载统一调用，确保两种模式的下载阶段都禁用 img2pdf
        插件，跨命令模式交替时插件状态一致无竞争。
        """
        pdf_path = self.download_root / "pdf" / f"{album_id}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        def _convert() -> None:
            import img2pdf
            with open(pdf_path, "wb") as f:
                f.write(img2pdf.convert(image_paths))

        await asyncio.to_thread(_convert)
        return str(pdf_path.resolve())

    async def _ensure_superres_binary(self, model: str):
        """确保指定超分工具的二进制存在，不存在则自动下载解压。

        返回 exe 的 Path，失败返回 None。
        """
        cfg = SUPERRES_TOOLS[model]
        label = cfg["label"]
        tool_dir = self.superres_dirs[model]
        exe_path = self.superres_exes[model]

        if exe_path.exists():
            return exe_path

        tool_dir.mkdir(parents=True, exist_ok=True)
        zip_path = tool_dir / cfg["zip_name"]

        try:
            logger.info(
                f"开始下载 {label} 二进制（{cfg['download_mb']}）: {cfg['zip_url']}"
            )

            def _download_zip():
                import urllib.request
                urllib.request.urlretrieve(cfg["zip_url"], str(zip_path))

            await asyncio.to_thread(_download_zip)

            def _extract_zip():
                import zipfile
                with zipfile.ZipFile(str(zip_path), "r") as zf:
                    zf.extractall(str(tool_dir))

            await asyncio.to_thread(_extract_zip)

            try:
                zip_path.unlink()
            except OSError:
                pass

            if exe_path.exists():
                logger.info(f"{label} 二进制已就绪: {exe_path}")
                return exe_path

            # 部分压缩包会多套一层目录，递归查找
            for exe in tool_dir.rglob(cfg["exe"]):
                logger.info(f"{label} 二进制找到于: {exe}")
                return exe

            logger.error(f"{label} 二进制解压后未找到: {tool_dir}")
            return None

        except Exception as e:
            logger.exception(f"{label} 二进制下载/解压失败: {e}")
            return None

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
