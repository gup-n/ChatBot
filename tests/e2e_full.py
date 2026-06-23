"""API E2E Test — 3-port architecture verification."""

import sys
import httpx

API = "http://127.0.0.1:8000/api"
c = httpx.Client(transport=httpx.HTTPTransport(retries=0), timeout=30)
P = 0
F = 0

def ok(cond, msg):
    global P, F
    if cond:
        P += 1
        print(f"  [PASS] {msg}")
    else:
        F += 1
        print(f"  [FAIL] {msg}")

# 1. Health
print("--- 1. Health ---")
r = c.get(f"{API}/health")
ok(r.status_code == 200, f"Health={r.status_code}")
d = r.json()
ok(d["status"] == "ok", "status=ok")
ok(d["warmed_up"] is True, "warmed_up=True")

# 2. Auth + Register
print("--- 2. Auth + Register ---")
r = c.post(f"{API}/auth/login", json={"username":"admin","password":"admin123"})
ok(r.status_code == 200, "Admin login=200")
ah = {"Authorization": f"Bearer {r.json()['access_token']}"}

# Register
r = c.post(f"{API}/auth/register", json={"username":"newuser42","password":"pass42"})
ok(r.status_code == 200, f"Register=200 (user: {r.json().get('username','?')})")

# Duplicate register
r = c.post(f"{API}/auth/register", json={"username":"newuser42","password":"x"})
ok(r.status_code == 400, "Dup register=400")

# Register login
r = c.post(f"{API}/auth/login", json={"username":"newuser42","password":"pass42"})
ok(r.status_code == 200, "New user login=200")
ok(r.json()["is_admin"] is False, "Not admin")
uh = {"Authorization": f"Bearer {r.json()['access_token']}"}

# Short password
r = c.post(f"{API}/auth/register", json={"username":"x","password":"ab"})
ok(r.status_code == 400, "Short pw register=400")

# 3. Admin Config
print("--- 3. Config ---")
ok(c.get(f"{API}/admin/config", headers=ah).status_code == 200, "GET config=200")
ok(c.put(f"{API}/admin/config", headers=ah, json={
    "provider":"deepseek","api_key":"sk-test","model":"deepseek-v4-flash","base_url":"https://api.deepseek.com"
}).status_code == 200, "PUT config=200")

# 4. Admin Users
print("--- 4. Users ---")
ok(c.get(f"{API}/admin/users", headers=ah).status_code == 200, "GET users=200")
r = c.post(f"{API}/admin/users", headers=ah, json={"username":"admin_created","password":"pass"})
ok(r.status_code == 200, "Admin create user=200")
uid = r.json()["id"]
ok(c.delete(f"{API}/admin/users/{uid}", headers=ah).status_code == 200, "Delete user=200")

# 5. Warmup
print("--- 5. Warmup ---")
ok(c.get(f"{API}/admin/status").status_code == 200, "Status=200")
ok(c.post(f"{API}/admin/warmup", headers=ah).status_code == 200, "Warmup=200")

# 6. Chat sessions
print("--- 6. Sessions ---")
r = c.post(f"{API}/chat/sessions", headers=uh)
ok(r.status_code == 200, "Create session=200")
sid = r.json()["id"]
ok(c.get(f"{API}/chat/sessions", headers=uh).status_code == 200, "List=200")
ok(c.get(f"{API}/chat/sessions/{sid}/messages", headers=uh).status_code == 200, "Msgs=200")
r = c.post(f"{API}/chat/send", headers=uh, json={"message":"Hi","session_id":sid})
ok(r.status_code == 200, f"Send={r.status_code} ({len(r.text)}b)")
ok(c.delete(f"{API}/chat/sessions/{sid}", headers=uh).status_code == 200, "Delete=200")

# 7. Streamlit pages
print("--- 7. Frontend ---")
import urllib.request
try:
    r1 = urllib.request.urlopen("http://127.0.0.1:8501", timeout=5)
    ok(r1.status == 200, "Admin page:200")
except Exception as e:
    ok(False, f"Admin page: {e}")
try:
    r2 = urllib.request.urlopen("http://127.0.0.1:8502", timeout=5)
    ok(r2.status == 200, "User page:200")
except Exception as e:
    ok(False, f"User page: {e}")

total = P + F
print(f"\n{'='*50}\n  PASSED: {P}/{total}")
sys.exit(0 if F == 0 else 1)
