"""
Integration Tests for FastAPI REST Endpoints and Chat Assistant.
Validates HTTP contracts, multi-turn follow-up context resolution,
health endpoints, and session management.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_serve_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Linux Laptop Hardware Q&A Assistant" in response.text


def test_api_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "platform" in data
    assert "tools_detected" in data


def test_api_hardware_endpoints():
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
        resp = client.get(ep)
        assert resp.status_code == 200, f"Failed on endpoint {ep}"
        data = resp.json()
        assert isinstance(data, dict)


def test_chat_ram_question_and_follow_up():
    """Tests primary RAM query and conversational follow-up resolution."""
    session_id = "test-session-ram"

    # Turn 1: Primary RAM question
    payload1 = {
        "message": "How much RAM do I have?",
        "session_id": session_id,
    }
    resp1 = client.post("/api/chat", json=payload1)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["category"] == "memory"
    assert "RAM" in data1["answer"] or "installed" in data1["answer"]

    # Turn 2: Follow-up question about available RAM
    payload2 = {
        "message": "How much is currently available?",
        "session_id": session_id,
    }
    resp2 = client.post("/api/chat", json=payload2)
    assert resp2.status_code == 200
    data2 = resp2.json()
    # Context should resolve to memory
    assert data2["category"] == "memory"
    assert "available" in data2["answer"].lower()

    # Turn 3: Follow-up transition to GPU ("What about my GPU?")
    payload3 = {
        "message": "What about my GPU?",
        "session_id": session_id,
    }
    resp3 = client.post("/api/chat", json=payload3)
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["category"] == "gpu"


def test_chat_storage_nvme_question():
    resp = client.post("/api/chat", json={"message": "Is my SSD NVMe or SATA?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "storage"
    assert "nvme" in data["answer"].lower() or "sata" in data["answer"].lower()


def test_chat_ram_upgrade_question():
    resp = client.post("/api/chat", json={"message": "Can I upgrade my RAM?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "ram_upgrade"
    assert "RAM" in data["answer"]


def test_chat_cpu_question():
    resp = client.post("/api/chat", json={"message": "What is my processor model?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "cpu"
    assert "processor" in data["answer"].lower() or "cpu" in data["answer"].lower()


def test_chat_clear_session():
    session_id = "test-session-clear"
    # Seed a message
    client.post("/api/chat", json={"message": "How much RAM do I have?", "session_id": session_id})
    
    # Clear session
    resp = client.post("/api/chat/clear", json={"session_id": session_id})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cleared"
