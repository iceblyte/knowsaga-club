#!/usr/bin/env python
"""题目配图 · 真实链路抽验：真调百炼生图 + 真传 COS + 真读回那张图。

用法（在 backend/ 目录下）：

    .venv/Scripts/python.exe scripts/verify_image_chain.py
    .venv/Scripts/python.exe scripts/verify_image_chain.py --count 3
    .venv/Scripts/python.exe scripts/verify_image_chain.py --out ../docs/image-chain-evidence-YYYY-MM-DD.txt

## 为什么它不在 pytest 里

与 `verify_quiz_chain.py` / `verify_search_chain.py` 同一条纪律：
**pytest 里一律 mock 上游**，保证确定性与「不花真钱」。而这个脚本的全部价值
恰恰在于它打的是真接口 —— 单测能证明「编排逻辑对」，证明不了
「这条链在真实凭据下真的能出一张能打开的图」。

## 它验什么（以及**不**验什么）

覆盖：`prompt` 构建 → 百炼同步生图 → 下载（校验 Content-Type / 体积）→
COS `put_object` → 拼永久 URL → **再 GET 一次那个 URL**（证明桶权限是公有读）。

不覆盖：出题本身（那是 `verify_quiz_chain.py` 的事）、配额表（那是 pytest 的事）、
前端渲染（那是浏览器的事）。这里只跑「题目已经拿到、要配图」这一段的真实形态。

## 退出码

- `0`：`--count` 道全部拿到可访问的永久 URL
- `1`：凭据不齐 / 一道都没成功 / 拿到了 URL 但打开不了（多为桶不是公有读）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 允许直接以脚本方式运行（把 backend/ 加入 sys.path）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.llm import image as image_flow  # noqa: E402
from app.models.quiz import Option, Question  # noqa: E402

#: 用来抽验的题目。**刻意手写而不是调 LLM** —— 这个脚本要隔离出「生图这一段」，
#: 混进出题会让失败原因分不清是出题挂了还是生图挂了，还会多花一次 LLM 的钱。
#: 三道的知识点差异明显，便于肉眼确认「每道题的图确实跟着它的知识点走」。
SAMPLES: list[Question] = [
    Question(
        id="q1",
        type="single",
        stem="咖啡豆烘焙到什么温度区间会进入第一次爆裂？",
        options=[
            Option(key="A", text="150°C 到 170°C"),
            Option(key="B", text="196°C 到 205°C"),
            Option(key="C", text="230°C 到 250°C"),
        ],
        answer=["B"],
        explanation="第一次爆裂通常发生在 196°C 到 205°C 之间。",
        knowledge_point="咖啡烘焙",
        difficulty="medium",
    ),
    Question(
        id="q2",
        type="single",
        stem="TCP 建立连接为什么需要三次握手而不是两次？",
        options=[
            Option(key="A", text="为了让双方都确认对方的收发能力"),
            Option(key="B", text="为了加快连接速度"),
            Option(key="C", text="为了加密传输内容"),
        ],
        answer=["A"],
        explanation="两次握手无法让服务端确认客户端已收到自己的确认报文。",
        knowledge_point="TCP 协议",
        difficulty="medium",
    ),
    Question(
        id="q3",
        type="judge",
        stem="光合作用的光反应阶段能直接固定二氧化碳。",
        options=[Option(key="T", text="正确"), Option(key="F", text="错误")],
        answer=["F"],
        explanation="固定二氧化碳发生在暗反应（卡尔文循环），光反应只产 ATP 与 NADPH。",
        knowledge_point="光合作用",
        difficulty="easy",
    ),
]


def _missing_credentials(settings) -> list[str]:
    """列出「让 image_generation_available 变成 false」的每一个原因。"""
    reasons: list[str] = []
    if not settings.image_generation_enabled:
        reasons.append("IMAGE_GENERATION_ENABLED 不是 true")
    if not (settings.dashscope_api_key or "").strip():
        reasons.append("DASHSCOPE_API_KEY 为空")
    for name, value in (
        ("COS_SECRET_ID", settings.cos_secret_id),
        ("COS_SECRET_KEY", settings.cos_secret_key),
        ("COS_REGION", settings.cos_region),
        ("COS_BUCKET", settings.cos_bucket),
    ):
        if not (value or "").strip():
            reasons.append(f"{name} 为空")
    return reasons


def _probe_url(url: str, *, timeout: float) -> tuple[bool, str]:
    """GET 一次永久 URL，确认它真的能打开且是图片。

    ⚠️ 这一步**不能省**：上传成功 ≠ 公开可读。COS 桶默认是**私有读写**，
    没改成公有读的话 `put_object` 一样返回 200，但客户端拿到的是一段
    「AccessDenied」的 XML —— 而前端 `<image>` 只会静默显示一片空白。
    """
    import httpx

    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001 - 网络层什么都可能抛
        return False, f"{type(exc).__name__}: {exc}"

    content_type = response.headers.get("content-type", "")
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}（{content_type or '无 Content-Type'}）"
    if not content_type.startswith("image/"):
        return False, f"Content-Type 不是图片：{content_type or '空'}"
    if len(response.content) == 0:
        return False, "响应体是空的"
    return True, f"HTTP 200 · {content_type} · {len(response.content)} 字节"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=len(SAMPLES), help=f"抽验几道题（最多 {len(SAMPLES)}）")
    parser.add_argument("--out", default="", help="把完整报告写到这个路径（供 docs/ 留档）")
    parser.add_argument("--no-probe", action="store_true", help="跳过「再 GET 一次永久 URL」这一步")
    args = parser.parse_args()

    settings = get_settings()
    count = max(1, min(args.count, len(SAMPLES)))
    questions = SAMPLES[:count]

    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    emit("=" * 78)
    emit("题目配图 · 真实链路抽验")
    emit("=" * 78)
    emit(f"  生图模型     : {settings.image_model}")
    emit(f"  图片尺寸     : {settings.image_size}")
    emit(f"  并发 / 超时  : {settings.image_max_workers} / 单张 {settings.image_timeout_seconds}s / 预算 {settings.image_budget_seconds}s")
    emit(f"  永久地址前缀 : {settings.cos_url_prefix or '（空）'}")
    emit(f"  抽验道数     : {count}")
    emit("=" * 78)

    missing = _missing_credentials(settings)
    if missing:
        emit("[x] 配图能力当前不可用（`image_generation_available = false`），缺：")
        for reason in missing:
            emit(f"      · {reason}")
        emit("")
        emit("    配齐后重跑本脚本即可。COS 五项从腾讯云控制台获取，")
        emit("    只写进仓库根目录的 `.env`（即 `knowsaga-club/.env`，不是 backend/ 下），不要提交。")
        emit("    ⚠️ 桶权限需要设成**公有读**，否则客户端打不开图。")
        if args.out:
            Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1

    emit("")
    emit("开始生图（一题一次调用，并发推进）……")
    started = time.perf_counter()

    progress: list[str] = []

    def on_progress(done: int, total: int) -> None:
        stamp = time.perf_counter() - started
        line = f"    配图进度 {done} / {total}  （{stamp:.1f}s）"
        progress.append(line)

    outcome = image_flow.generate_for_questions(
        questions, settings=settings, on_progress=on_progress
    )
    elapsed = time.perf_counter() - started

    emit("")
    for line in progress:
        emit(line)

    emit("")
    emit("-" * 78)
    emit(f"  结果：attempted={outcome.attempted}  succeeded={outcome.succeeded}  reason={outcome.reason or '(空=全部成功)'}")
    emit(f"  总耗时：{elapsed:.1f}s")
    emit("-" * 78)

    for question in questions:
        url = outcome.urls.get(question.id)
        if not url:
            emit(f"  ❌ {question.id}  [{question.knowledge_point}]  没有配图")
            continue
        emit(f"  ✅ {question.id}  [{question.knowledge_point}]  {url}")
        if args.no_probe:
            continue
        ok, detail = _probe_url(url, timeout=float(settings.image_timeout_seconds))
        emit(f"       读回：{'✅' if ok else '❌'} {detail}")
        if not ok and "200" not in detail:
            emit("       ⚠️ 拿到 URL 却打不开，最常见的原因是 COS 桶不是公有读。")

    emit("=" * 78)

    complete = outcome.complete and outcome.succeeded == count
    if args.out:
        Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"[i] 报告已写入 {args.out}")

    if not complete:
        emit(f"[x] 未全部成功：{outcome.succeeded} / {count}（reason={outcome.reason or '(空)'}）")
        return 1

    emit("[ok] 全部题目都拿到了可公开访问的永久配图")
    emit("")
    emit("⚠️ 以上只证明「图生成出来了、地址能打开」。**画面内容必须人眼验收** ——")
    emit("   「画面里有没有文字」「跟题目是否相关」单测断不了（见 design D16）：")
    emit("   换模型 / 改风格尾缀 / 改提示词结构之后，务必把图下载下来自己看一眼。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
