"""健康检查接口测试（对应 Phase 0.2）。

覆盖点：
- HTTP 200
- 统一响应结构 `{code, message, data}`
- `code == 0`
- `data` 字段完整性：status / version / model / search_enabled / knowledge_base_enabled /
  image_generation_enabled / key_configured
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
        "image_generation_enabled",
        "key_configured",
    ):
        assert field in data, f"缺少字段 {field}"
    assert data["status"] == "healthy"
    assert isinstance(data["search_enabled"], bool)
    assert isinstance(data["knowledge_base_enabled"], bool)
    assert isinstance(data["image_generation_enabled"], bool)
    assert isinstance(data["key_configured"], bool)


def test_health_discloses_the_knowledge_base_flag(client: TestClient) -> None:
    """开关值必须**如实**下发（前端据此决定四处入口显不显示，design D18）。

    测试基线没有打开 `KNOWLEDGE_BASE_ENABLED`，所以这里期望 `False` ——
    它同时也是「默认关 ⇒ 前端默认看不见入口」这条约定的机器化写法。
    """
    data = client.get("/api/v1/health").json()["data"]

    assert data["knowledge_base_enabled"] is False, "基线环境没开知识库，不许谎报为 True"


def test_health_discloses_the_image_generation_flag(client: TestClient) -> None:
    """配图能力同样要**如实**下发，而且它下发的必须是**派生能力**而不是裸开关。

    `image_generation_enabled` 取的是 `image_generation_available` ——
    「开关打开 **且** 百炼 key **且** COS 五项齐全」三者同时成立才为真。
    只下发裸开关的话，会出现「开关是 true 但缺 COS 凭据」⇒ 前端显示开关 ⇒
    用户点下去必然失败（design D7：宁可少一个入口，也不给一个点了必失败的按钮）。

    测试基线三项都不满足，所以期望 `False`。
    """
    data = client.get("/api/v1/health").json()["data"]

    assert data["image_generation_enabled"] is False, "基线环境没有配图凭据，不许谎报为 True"


def test_health_image_flag_tracks_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """打开开关但**不给凭据**时，对外仍必须是 `False`（能力而非意愿）。

    ⚠️ 这里**显式**把 COS 凭据清空，而不是依赖基线为空：本机 `.env` 做端到端验收时
    是真配了 COS 凭据的，不清的话这条用例会随本机环境红/绿（2026-09-26 实锤过一次）。
    """
    from app.core.config import get_settings

    for key in ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_REGION", "COS_BUCKET"):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
    get_settings.cache_clear()

    data = client.get("/api/v1/health").json()["data"]

    assert data["image_generation_enabled"] is False, "缺 COS 凭据时不该对外宣告可用"


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
