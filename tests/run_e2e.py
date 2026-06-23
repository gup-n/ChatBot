"""E2E test runner - starts servers, runs tests, stops servers."""

import subprocess, sys, time, os, signal

PROJECT_DIR = "c:/Users/14428/Desktop/coding/python/ChatBot"


def main():
    # Clean DB
    db_path = os.path.join(PROJECT_DIR, "data", "chatbot.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    print("[1] DB cleaned", flush=True)

    # Start FastAPI
    print("[2] Starting FastAPI...", flush=True)
    api_log = open(os.path.join(PROJECT_DIR, "data", "api.log"), "w")
    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--port", "8000", "--host", "0.0.0.0", "--log-level", "debug"],
        cwd=PROJECT_DIR,
        stdout=api_log,
        stderr=subprocess.STDOUT,
    )
    time.sleep(3)

    # Verify FastAPI is up
    import httpx
    for i in range(10):
        try:
            r = httpx.get("http://127.0.0.1:8000/api/health", timeout=5)
            if r.status_code == 200:
                print(f"[2] FastAPI ready (attempt {i+1})", flush=True)
                break
        except Exception:
            time.sleep(1)
    else:
        print("[2] FastAPI failed to start", flush=True)
        api.terminate()
        sys.exit(1)

    # Start Streamlit
    print("[3] Starting Streamlit...", flush=True)
    st = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "frontend/app.py",
         "--server.port", "8501", "--server.headless", "true", "--server.address", "0.0.0.0"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for i in range(15):
        try:
            r = httpx.get("http://127.0.0.1:8501", timeout=5)
            if r.status_code == 200:
                print(f"[3] Streamlit ready (attempt {i+1})", flush=True)
                break
        except Exception:
            time.sleep(1)
    else:
        print("[3] Streamlit may not be ready, continuing anyway...", flush=True)
    time.sleep(2)

    # Run the test
    print("[4] Running tests...", flush=True)
    result = subprocess.run(
        [sys.executable, "tests/e2e_test.py"],
        cwd=PROJECT_DIR,
        timeout=240,  # 4 minutes for warmup
    )

    # Cleanup
    print("[5] Stopping servers...", flush=True)
    st.terminate()
    api.terminate()
    st.wait()
    api.wait()
    print("[5] Done", flush=True)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
