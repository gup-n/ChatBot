"""一键启动 — FastAPI + 管理员控制台 + 用户聊天系统。

用法:
    python run.py                # 启动全部 3 个服务
    python run.py --backend       # 仅启动后台 API

访问:
    后端 API:     http://localhost:8000/docs
    管理员控制台: http://localhost:8501  (admin/admin123)
    用户聊天系统: http://localhost:8502  (注册后登录)
"""

import subprocess, sys, time, os


def main():
    start_backend = "--user" not in sys.argv and "--admin" not in sys.argv
    start_admin = "--backend" not in sys.argv and "--user" not in sys.argv
    start_user = "--backend" not in sys.argv and "--admin" not in sys.argv

    if "--backend" in sys.argv:
        start_admin = False
        start_user = False

    procs = []

    # ── 1. FastAPI 后端 ──
    if start_backend:
        print("[run] FastAPI 后端 (端口 8000)...")
        api = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--host", "0.0.0.0", "--port", "8000",
        ])
        procs.append(("FastAPI", api))
        time.sleep(2)

    # ── 2. 管理员控制台 ──
    if start_admin:
        print("[run] 管理员控制台 (端口 8501)...")
        admin = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", "frontend/admin/app.py",
            "--server.address", "0.0.0.0", "--server.port", "8501",
            "--server.headless", "true",
            "--server.enableXsrfProtection", "false",
            "--server.enableCORS", "false",
        ])
        procs.append(("Admin", admin))
        time.sleep(3)

    # ── 3. 用户聊天系统 ──
    if start_user:
        print("[run] 用户聊天系统 (端口 8502)...")
        user = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", "frontend/user/app.py",
            "--server.address", "0.0.0.0", "--server.port", "8502",
            "--server.headless", "true",
            "--server.enableXsrfProtection", "false",
            "--server.enableCORS", "false",
        ])
        procs.append(("User", user))
        time.sleep(3)

    print()
    print("=" * 55)
    print("  网安学院问答机器人 — 已启动")
    print()
    print("  后端 API:      http://localhost:8000/docs")
    print("  管理员控制台:  http://localhost:8501")
    print("  用户聊天系统:  http://localhost:8502")
    print()
    print("  管理员: admin / admin123")
    print("  用户:   自行注册或管理员添加")
    print("  按 Ctrl+C 停止所有服务")
    print("=" * 55)

    try:
        for _, proc in procs:
            proc.wait()
    except KeyboardInterrupt:
        print("\n[run] 正在关闭...")
        for _, proc in procs:
            proc.terminate()
            proc.wait()
        print("[run] 已停止")


if __name__ == "__main__":
    main()
