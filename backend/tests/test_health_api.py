"""健康检查接口测试（对应 Phase 0.2）。

覆盖点：
- HTTP 200
- 统一响应结构 `{code, message, data}`
- `code == 0`
- `data` 字段完整性：status / version / model / search_enabled / knowledge_base_enabled /
  key_configured
- **不泄漏密钥**（响应体中不得出现 sk- 开头的字符串）

## 为什么 `knowledge_base_enabled` 要从健康检查下发

它是前端四处入口（工坊两行 / 我的 / 大厅 chip）显隐的**唯一事实来源**（design D18）。
如果前端自己配一份，两边迟早漂移：后端关掉了、前端还显示入口，用户点进去
一路走到上传才会撞墙。让它随 `/health` 一起下发，等于把「显不显示」绑定在
「后端到底开没开」这个事实上。

⚠️ 它**不是**权限位：`/kb/*` 路由无条件注册，关掉时接口照样能调。
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
    for field in (
        "status",
        "version",
        "env",
        "model",
        "search_enabled",
        "knowledge_base_enabled",
        "key_configured",
    ):
        assert field in data, f"缺少字段 {field}"
    assert data["status"] == "healthy"
    assert isinstance(data["search_enabled"], bool)
    assert isinstance(data["knowledge_base_enabled"], bool)
    assert isinstance(data["key_configured"], bool)


def test_health_discloses_the_knowledge_base_flag(client: TestClient) -> None:
    """开关值必须**如实**下发（前端据此决定四处入口显不显示，design D18）。

    测试基线没有打开 `KNOWLEDGE_BASE_ENABLED`，所以这里期望 `False` ——
    它同时也是「默认关 ⇒ 前端默认看不见入口」这条约定的机器化写法。
    """
    data = client.get("/api/v1/health").json()["data"]

    assert data["knowledge_base_enabled"] is False, "基线环境没开知识库，不许谎报为 True"


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
