"""
End-to-End Live Server Verification Script.
Queries the running FastAPI server, checks the web frontend, tests API endpoints,
and performs multi-turn natural language questions.
"""

import sys
import httpx

BASE_URL = "http://127.0.0.1:8000"

def run_verification():
    print(f"[*] Testing connection to {BASE_URL}...")
    try:
        with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
            # 1. Test frontend
            r_index = client.get("/")
            assert r_index.status_code == 200, f"Frontend failed: {r_index.status_code}"
            assert "Linux Laptop Hardware Q&A Assistant" in r_index.text
            print("[+] GET / (Frontend Interface) -> 200 OK")

            # 2. Test Health
            r_health = client.get("/api/health")
            assert r_health.status_code == 200
            print(f"[+] GET /api/health -> 200 OK | Platform: {r_health.json()['platform']}")

            # 3. Test Hardware Endpoints
            endpoints = [
                "/api/hardware",
                "/api/hardware/cpu",
                "/api/hardware/memory",
                "/api/hardware/storage",
                "/api/hardware/gpu",
                "/api/hardware/motherboard",
                "/api/hardware/os",
                "/api/hardware/ram-upgrade",
            ]
            for ep in endpoints:
                r = client.get(ep)
                assert r.status_code == 200, f"Endpoint {ep} failed: {r.status_code}"
                print(f"[+] GET {ep} -> 200 OK")

            # 4. Test 5+ Natural Language Questions and Follow-ups
            test_questions = [
                ("How much RAM do I have?", "memory"),
                ("How much is currently available?", "memory"),  # Follow-up
                ("Is my SSD NVMe or SATA?", "storage"),
                ("What is my processor model?", "cpu"),
                ("How many CPU cores do I have?", "cpu"),
                ("What GPU does my laptop have?", "gpu"),
                ("Can I upgrade my RAM?", "ram_upgrade"),
                ("What Linux operating system am I running?", "os"),
                ("Show my complete hardware details.", "all_hardware"),
            ]

            session_id = "live-verify-session-1"
            print("\n[*] Testing Natural Language Questions & Follow-ups:")
            for q, expected_cat in test_questions:
                payload = {"message": q, "session_id": session_id}
                r_chat = client.post("/api/chat", json=payload)
                assert r_chat.status_code == 200, f"Chat failed for '{q}': {r_chat.text}"
                resp = r_chat.json()
                print(f"\n  Q: \"{q}\"")
                print(f"  Category: {resp['category']} (Expected: {expected_cat}) | Source: {resp['source']}")
                print(f"  Answer: {resp['answer']}")
                assert resp["category"] == expected_cat, f"Mismatch for '{q}': got {resp['category']}"

            print("\n[SUCCESS] All Live Server Endpoints and Chat Queries Verified Successfully!")
            return 0
    except Exception as exc:
        print(f"\n[ERROR] Verification failed: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(run_verification())
