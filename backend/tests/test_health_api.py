"""健康检查接口测试（对应 Phase 0.2）。

覆盖点：
- HTTP 200
- 统一响应结构 `{code, message, data}`
- `code == 0`
- `data` 字段完整性：status / version / model / search_enabled / key_configured
- **不泄漏密钥**（响应体中不得出现 sk- 开头的字符串）
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_health_unified_response_shape(client: TestClient) -> None:
    """响应体必须是 {code, message, data} 三键，且 code 为 0。"""
    body = client.get("/api/v1/health").json()
    assert set(body.keys()) == {"code", "message", "data"}
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert isinstance(body["data"], dict)


def test_health_data_fields(client: TestClient) -> None:
    """data 必须包含前端与运维需要的全部字段。"""
    data = client.get("/api/v1/health").json()["data"]
    for field in ("status", "version", "env", "model", "search_enabled", "key_configured"):
        assert field in data, f"缺少字段 {field}"
    assert data["status"] == "healthy"
    assert isinstance(data["search_enabled"], bool)
    assert isinstance(data["key_configured"], bool)


def test_health_reports_configured_model(client: TestClient) -> None:
    """必须回报当前实际使用的模型名，便于排查模型名写错的问题。"""
    data = client.get("/api/v1/health").json()["data"]
    assert data["model"] == "deepseek-flash"
    assert data["key_configured"] is True


def test_health_never_leaks_api_key(client: TestClient) -> None:
    """密钥绝不能出现在任何响应里。"""
    raw = client.get("/api/v1/health").text
    assert "sk-" not in raw
    assert json.loads(raw)["data"].get("deepseek_api_key") is None
