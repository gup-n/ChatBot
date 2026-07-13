"""一键启动 — FastAPI + 管理员控制台 + 用户聊天系统。

用法:
    python run.py                # 启动全部 3 个服务
    python run.py --backend       # 仅启动后台 API

访问:
    后端 API:     http://localhost:8000/docs
    管理员控制台: http://localhost:8501  (admin/admin123)
    用户聊天系统: http://localhost:8502  (注册后登录)
"""

import os
import subprocess, sys, time

APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
API_PORT = os.getenv("API_PORT", "8000")
ADMIN_PORT = os.getenv("ADMIN_PORT", "8501")
USER_PORT = os.getenv("USER_PORT", "8502")


def _frontend_env() -> dict[str, str]:
    """前端未显式配置 API 地址时，自动跟随本次后端端口。"""
    env = os.environ.copy()
    env.setdefault("STREAMLIT_API_URL", f"http://127.0.0.1:{API_PORT}/api")
    return env


def _shutdown(procs):
    """先 terminate，5 秒后未退出则 force kill。"""
    for name, proc in procs:
        if proc.poll() is None:
            print(f"[run] 关闭 {name} (PID {proc.pid})...")
            # Windows 下 terminate 等价于 kill，直接发
            proc.terminate()
    # 等 5 秒让进程优雅退出
    deadline = time.time() + 5
    for name, proc in procs:
        remaining = deadline - time.time()
        if remaining > 0 and proc.poll() is None:
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
    # 还没死的强制 kill
    for name, proc in procs:
        if proc.poll() is None:
            print(f"[run] 强制终止 {name} (PID {proc.pid})...")
            proc.kill()
            proc.wait()


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
        print(f"[run] FastAPI 后端 (端口 {API_PORT})...")
        api = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "backend.main:app",
            "--host", APP_HOST, "--port", API_PORT,
        ])
        procs.append(("FastAPI", api))
        time.sleep(2)

    # ── 2. 管理员控制台 ──
    if start_admin:
        print(f"[run] 管理员控制台 (端口 {ADMIN_PORT})...")
        admin = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", "frontend/admin/app.py",
            "--server.address", APP_HOST, "--server.port", ADMIN_PORT,
            "--server.headless", "true",
            "--server.enableXsrfProtection", "false",
            "--server.enableCORS", "false",
        ], env=_frontend_env())
        procs.append(("Admin", admin))
        time.sleep(3)

    # ── 3. 用户聊天系统 ──
    if start_user:
        print(f"[run] 用户聊天系统 (端口 {USER_PORT})...")
        user = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run", "frontend/user/app.py",
            "--server.address", APP_HOST, "--server.port", USER_PORT,
            "--server.headless", "true",
            "--server.enableXsrfProtection", "false",
            "--server.enableCORS", "false",
        ], env=_frontend_env())
        procs.append(("User", user))
        time.sleep(3)

    print()
    print("=" * 55)
    print("  网安学院问答机器人 — 已启动")
    print()
    print(f"  后端 API:      http://localhost:{API_PORT}/docs")
    print(f"  管理员控制台:  http://localhost:{ADMIN_PORT}")
    print(f"  用户聊天系统:  http://localhost:{USER_PORT}")
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
        _shutdown(procs)
        print("[run] 已停止")


if __name__ == "__main__":
    main()
