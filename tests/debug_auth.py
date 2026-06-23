"""Minimal debug script: Test backend API directly."""

import httpx

url = "http://127.0.0.1:8000/api/auth/login"

try:
    r = httpx.post(url, json={"username": "admin", "password": "admin123"}, timeout=10)
    print(f"Status: {r.status_code}")
    print(f"Headers: {dict(r.headers)}")
    print(f"Body: {r.text[:500]}")
    print(f"Content-Type: {r.headers.get('content-type', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")
