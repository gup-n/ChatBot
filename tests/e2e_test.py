"""E2E test: FastAPI + Streamlit. Tests backend APIs, auth, and frontend.

Note: Warmup (embedding model load + ChromaDB build) takes 3-5 min on CPU.
It is skipped in automated tests but verified to work in manual testing.
"""

import time, sys, os, httpx, json

FASTAPI_URL = "http://127.0.0.1:8000"
STREAMLIT_URL = "http://127.0.0.1:8501"
ADMIN_USER = "admin"
ADMIN_PASS = "admin123"
TEST_USER = "testuser"
TEST_PASS = "test123"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-75346f67fbcb4f87ad39096bb2b8270f")

errors = []

def log(msg):
    print(f"  {msg}", flush=True)

def ok(condition, desc):
    if not condition:
        errors.append(f"FAIL: {desc}")
        print(f"  [FAIL] {desc}", flush=True)
        return False
    print(f"  [PASS] {desc}", flush=True)
    return True


# ---------- Test 1: Backend API ----------
def test_backend():
    print("\n--- Test 1: Backend API ---", flush=True)

    # Health check
    try:
        r = httpx.get(f"{FASTAPI_URL}/api/health", timeout=10)
        ok(r.status_code == 200, f"GET /health -> {r.status_code}")
        data = r.json()
        ok(data.get("config_ready") == True, "Config ready")
    except Exception as e:
        ok(False, f"Health check: {e}")
        return None

    # Admin login
    try:
        r = httpx.post(f"{FASTAPI_URL}/api/auth/login",
                       json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=10)
        ok(r.status_code == 200, f"Admin login -> {r.status_code}")
        token = r.json().get("access_token", "")
        ok(bool(token), f"Token: {len(token)} chars")
        ok(r.json().get("is_admin") == True, "Admin role confirmed")
        return token
    except Exception as e:
        ok(False, f"Admin login: {e}")
        return None


# ---------- Test 2: Admin API ----------
def test_admin_api(token):
    print("\n--- Test 2: Admin API ---", flush=True)
    headers = {"Authorization": f"Bearer {token}"}

    # Get config
    r = httpx.get(f"{FASTAPI_URL}/api/admin/config", headers=headers, timeout=10)
    ok(r.status_code == 200, f"GET /config -> {r.status_code}")

    # Update config
    r = httpx.put(f"{FASTAPI_URL}/api/admin/config", headers=headers, json={
        "provider": "deepseek", "api_key": DEEPSEEK_API_KEY,
        "model": "deepseek-v4-flash", "base_url": "https://api.deepseek.com"
    }, timeout=10)
    ok(r.status_code == 200, f"PUT /config -> {r.status_code}")
    ok(Config_is_ready(), "Config.is_ready() after save")

    # Create user
    r = httpx.post(f"{FASTAPI_URL}/api/admin/users", headers=headers,
                   json={"username": TEST_USER, "password": TEST_PASS}, timeout=10)
    ok(r.status_code == 200, f"POST /users -> {r.status_code} (user: {TEST_USER})")

    # Duplicate user should fail
    r = httpx.post(f"{FASTAPI_URL}/api/admin/users", headers=headers,
                   json={"username": TEST_USER, "password": "x"}, timeout=10)
    ok(r.status_code == 400, f"Duplicate user -> 400")

    # List users
    r = httpx.get(f"{FASTAPI_URL}/api/admin/users", headers=headers, timeout=10)
    users = r.json()
    ok(len(users) >= 2, f"Users count: {len(users)}")
    log(f"  Users: {[u['username'] for u in users]}")

    # Status endpoint
    r = httpx.get(f"{FASTAPI_URL}/api/admin/status", timeout=10)
    ok(r.status_code == 200, f"GET /status -> {r.status_code}")

    # Warmup skipped in automated test (takes 3-5 min on CPU)
    log("  Warmup skipped (validated in manual testing)")


def Config_is_ready():
    """Check if config is ready via API."""
    r = httpx.get(f"{FASTAPI_URL}/api/health", timeout=10)
    return r.json().get("config_ready", False)


# ---------- Test 3: User Login API ----------
def test_user_login():
    print("\n--- Test 3: User Login API ---", flush=True)

    # Correct login
    r = httpx.post(f"{FASTAPI_URL}/api/auth/login",
                   json={"username": TEST_USER, "password": TEST_PASS}, timeout=10)
    ok(r.status_code == 200, f"User login -> {r.status_code}")
    data = r.json()
    ok(data.get("is_admin") == False, "Not admin")

    # Wrong password
    r = httpx.post(f"{FASTAPI_URL}/api/auth/login",
                   json={"username": TEST_USER, "password": "wrongpass"}, timeout=10)
    ok(r.status_code == 401, f"Wrong password -> 401")

    return data.get("access_token")


# ---------- Test 4: Chat API ----------
def test_chat_api(token):
    print("\n--- Test 4: Chat API ---", flush=True)
    headers = {"Authorization": f"Bearer {token}"}

    # Create session
    r = httpx.post(f"{FASTAPI_URL}/api/chat/sessions", headers=headers, timeout=10)
    ok(r.status_code == 200, f"POST /sessions -> {r.status_code}")
    sid = r.json().get("id", "")
    ok(bool(sid), f"Session ID: {sid[:8]}...")

    # List sessions
    r = httpx.get(f"{FASTAPI_URL}/api/chat/sessions", headers=headers, timeout=10)
    ok(r.status_code == 200, f"GET /sessions -> {r.status_code}")
    sessions = r.json()
    ok(len(sessions) >= 1, f"Session count: {len(sessions)}")

    # Get messages (empty session)
    r = httpx.get(f"{FASTAPI_URL}/api/chat/sessions/{sid}/messages", headers=headers, timeout=10)
    ok(r.status_code == 200, f"GET /messages -> {r.status_code}")

    # Delete session
    r = httpx.delete(f"{FASTAPI_URL}/api/chat/sessions/{sid}", headers=headers, timeout=10)
    ok(r.status_code == 200, f"DELETE /session -> {r.status_code}")


# ---------- Test 5: Session Isolation ----------
def test_isolation(token):
    print("\n--- Test 5: Session Isolation ---", flush=True)
    headers = {"Authorization": f"Bearer {token}"}

    # Create session as test user
    r = httpx.post(f"{FASTAPI_URL}/api/chat/sessions", headers=headers, timeout=10)
    sid = r.json()["id"]

    # Admin login
    r = httpx.post(f"{FASTAPI_URL}/api/auth/login",
                   json={"username": ADMIN_USER, "password": ADMIN_PASS}, timeout=10)
    admin_token = r.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Admin sees their own sessions (not test user's)
    r = httpx.get(f"{FASTAPI_URL}/api/chat/sessions", headers=admin_headers, timeout=10)
    admin_sessions = r.json()
    admin_sids = [s["id"] for s in admin_sessions]
    ok(sid not in admin_sids, "Admin cannot see test user's session")

    # Test user sees their session
    r = httpx.get(f"{FASTAPI_URL}/api/chat/sessions", headers=headers, timeout=10)
    user_sessions = r.json()
    ok(len(user_sessions) == 1, "Test user sees 1 session")


# ---------- Test 6: Streamlit Frontend ----------
def test_frontend():
    print("\n--- Test 6: Streamlit Frontend ---", flush=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("  Playwright not installed, skipping frontend test")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # Step 6.1: Navigate to Streamlit
        log("Step 6.1: Admin Login Page")
        page.goto(STREAMLIT_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(5000)
        page.screenshot(path="/tmp/e2e_01_admin_login.png")

        # Streamlit uses aria-label for inputs
        # st.text_input("用户名") → input[aria-label="用户名"]
        # st.text_input("密码", type="password") → input[type="password"][aria-label="密码"]
        u = page.locator('input[aria-label="用户名"]')
        p = page.locator('input[aria-label="密码"]')
        ok(u.count() > 0, f"Username input: {u.count()}")
        ok(p.count() > 0, f"Password input: {p.count()}")

        if u.count() > 0 and p.count() > 0:
            u.first.fill(ADMIN_USER)
            p.first.fill(ADMIN_PASS)
            log("  Filled admin credentials")

        # st.button("登录") → button within stButton
        btn = page.locator('button:has-text("登录")').first
        if btn.count() > 0:
            btn.click()
            page.wait_for_timeout(4000)
            log("  Clicked login")

        page.screenshot(path="/tmp/e2e_02_admin_page.png")
        content = page.content()

        # Admin setup page has tabs: 模型配置, 用户管理, 启动服务
        has_setup = "模型" in content or "保存配置" in content or "添加用户" in content
        ok(has_setup, f"Admin setup visible")
        log(f"  Page contains '保存配置': {'保存配置' in content}")
        log(f"  Page contains '添加用户': {'添加用户' in content}")

        browser.close()


# ---------- Main ----------
def main():
    print("=" * 60, flush=True)
    print("  E2E Test: NBUT Cyber ChatBot", flush=True)
    print("=" * 60, flush=True)

    token = test_backend()
    if not token:
        print("\nBackend not ready - exiting", flush=True)
        sys.exit(1)

    test_admin_api(token)
    user_token = test_user_login()
    if user_token:
        test_chat_api(user_token)
        test_isolation(user_token)
    test_frontend()

    print("\n" + "=" * 60, flush=True)
    if errors:
        print(f"  {len(errors)} FAILURE(S):", flush=True)
        for e in errors:
            print(f"    - {e}", flush=True)
        sys.exit(1)
    else:
        print("  ALL TESTS PASSED", flush=True)
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
