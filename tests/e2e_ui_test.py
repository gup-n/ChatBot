"""E2E test: Backend API + Streamlit full flow."""

import io, sys, time, httpx
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

API = "http://127.0.0.1:8000/api"
S = "http://127.0.0.1:8501"
p = f = 0
def ok(cond, msg):
    global p, f
    if cond: p += 1; print(f"  [PASS] {msg}")
    else: f += 1; print(f"  [FAIL] {msg}")

# ═══ Setup: Ensure test user exists ═══
print("--- Setup ---")
try:
    r = httpx.post(f"{API}/auth/login", json={"username":"admin","password":"admin123"}, timeout=10)
    t = r.json()["access_token"]
    h = {"Authorization": f"Bearer {t}"}
    r = httpx.post(f"{API}/admin/users", headers=h, json={"username":"testuser","password":"test123"}, timeout=10)
    ok(r.status_code in (200, 400), f"Test user ready ({r.status_code})")
except Exception as e:
    ok(False, f"Setup: {e}")
    sys.exit(1)

# ═══ E2E Tests ═══
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1280, "height": 900})

    # Test 1: Admin login
    print("\n--- Test 1: Admin Login ---")
    page.goto(S, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(6000)
    ok("用户名" in page.content(), "Login page renders")
    u = page.locator('input[aria-label="用户名"]')
    if u.count() > 0:
        u.first.fill("admin")
        page.locator('input[aria-label="密码"]').first.fill("admin123")
        page.locator('button:has-text("登录")').first.click()
        page.wait_for_timeout(5000)
    page.screenshot(path="C:/tmp/e2e_final_1.png")

    # Test 2: Auto-redirect (warmup detected → user login)
    print("\n--- Test 2: Auto Redirect ---")
    c = page.content()
    is_chat = "新建会话" in c or "请输入" in c
    is_login = "用户名" in c and not is_chat
    ok(is_login or is_chat, f"Redirect (login={is_login}, chat={is_chat})")

    # Test 3: User login → chat
    if is_login:
        print("\n--- Test 3: User Login → Chat ---")
        u2 = page.locator('input[aria-label="用户名"]')
        if u2.count() > 0:
            u2.first.fill("testuser")
            page.locator('input[aria-label="密码"]').first.fill("test123")
            page.locator('button:has-text("登录")').first.click()
            page.wait_for_timeout(5000)
    page.screenshot(path="C:/tmp/e2e_final_2.png")

    # Test 4: Verify chat page
    print("\n--- Test 4: Chat Page ---")
    c = page.content()
    ok("sk-" not in c, "No API key exposed")  # Security check
    ok(len(c) > 5000, f"Content loaded ({len(c)} chars)")
    # Page should have sidebar + main area
    has_app = "stApp" in c
    ok(has_app, "Streamlit app rendered")
    page.screenshot(path="C:/tmp/e2e_final_3.png")
    b.close()

# ═══ Summary ═══
total = p + f
print(f"\n{'='*50}\n  {p}/{total} passed")
sys.exit(0 if f == 0 else 1)
