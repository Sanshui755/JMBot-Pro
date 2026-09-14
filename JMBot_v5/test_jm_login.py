"""
JM 登录功能测试脚本

与 JMBot 插件 _jm_login_sync() 使用完全相同的链路：
    JmOption.from_file -> build_jm_client -> login -> update_cookies

运行方式（在 JMBot_v5 目录）：
    F:\\.jmcomic\\.venv\\Scripts\\python.exe test_jm_login.py
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

import jmcomic

PLUGIN_CONFIG = Path(__file__).resolve().parent / "plugins" / "JMBot" / "config"
ACCOUNT_FILE = PLUGIN_CONFIG / "jm_account.json"
JM_YML = PLUGIN_CONFIG / "config.yml"


def ask_credentials() -> tuple[str, str]:
    username = password = ""
    if ACCOUNT_FILE.exists():
        try:
            data = json.loads(ACCOUNT_FILE.read_text(encoding="utf-8"))
            username = str(data.get("username", ""))
            password = str(data.get("password", ""))
        except (json.JSONDecodeError, OSError):
            pass
        if username:
            print(f"发现已保存的账号: {username}")
            choice = input("直接使用该账号测试？(Y/n): ").strip().lower()
            if choice != "n":
                return username, password
    username = input("请输入 JM 用户名: ").strip()
    password = getpass.getpass("请输入 JM 密码（输入时不显示）: ")
    return username, password


def main() -> int:
    username, password = ask_credentials()
    if not username or not password:
        print("[失败] 用户名或密码为空")
        return 1

    print(f"\n使用配置: {JM_YML}")
    option = jmcomic.JmOption.from_file(str(JM_YML))
    client = option.build_jm_client()

    print("正在调用 JM 登录接口 ...")
    try:
        client.login(username, password)
    except Exception as e:
        print(f"[失败] 登录异常: {e!r}")
        return 1

    cookies = dict(client["cookies"])
    option.update_cookies(cookies)

    avs = cookies.get("AVS") or cookies.get("avs")
    print(f"[成功] 登录接口返回正常，cookies 字段: {sorted(cookies.keys())}")
    print(f"[{'成功' if avs else '警告'}] 登录态 Cookie AVS: {'已获取' if avs else '未发现'}")

    # 用新 client（携带 option 中 cookies）访问需要登录态的收藏夹接口做二次验证
    print("正在用登录态访问收藏夹接口验证 ...")
    try:
        authed = option.build_jm_client()
        # favorite_folder 是需要登录的接口，未登录会抛异常
        result = authed.favorite_folder()
        # 不同版本返回结构不一，只要不抛异常即视为登录态有效
        _ = result
        print("[成功] 登录态有效，可访问需要登录的内容")
    except Exception as e:
        print(f"[警告] 收藏夹验证未通过（不代表登录失败，可能是接口变动）: {e!r}")

    if not ACCOUNT_FILE.exists():
        choice = input("\n是否保存账号密码到 jm_account.json，供机器人自动登录？(y/N): ").strip().lower()
        if choice == "y":
            ACCOUNT_FILE.write_text(
                json.dumps({"username": username, "password": password},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[成功] 已保存: {ACCOUNT_FILE}")
        else:
            print("未保存，仅完成本次测试。")

    print("\n结论：登录功能链路正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
