"""联网检索 Provider 抽象层。

## 这一层解决什么

取材（联网检索 + 按 URL 读整页）是出题的**增强项**：它能让题目基于模型训练数据之外的新资料，
但它绝不该把出题任务拖垮。所以这一层的契约只有一句话 ——
**`gather()` 不允许抛异常**，取不到资料就降级，出题照常进行。

## 为什么「进度条第一步叫什么」也在接口里

原型的「副本召唤中」屏第一步的文案随取材方式而变（联网时「联网检索知识」、
读用户给的链接时「读取你给的网页」、完全不联网时「理解你的输入」）。
如果前端自己判断该显示哪个，后续改取材方式就得改前端 ——
所以约定：**provider 决定步骤名与详情，前端只负责渲染**（`docs/MVP开发计划.md` §7.3）。

⚠️ 因此步骤名必须**诚实**：它回答「这一步在做什么」，不回答「做成了没有」。
做了什么由 `first_step()` 的 detail 说，两者不要互相冒充（见 design 冲突点 14）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

#: 资料的形态：`snippet` = 检索摘要片段，`page` = 按 URL 抓到的整页正文
ResultKind = Literal["snippet", "page"]

#: 资料的来源：`user` = 用户自己在输入里给的链接，`web` = AI 主动检索到的，
#: `kb` = 用户自己的知识库（上传解析入库的文档片段）
ResultSource = Literal["user", "web", "kb"]

#: 知识库片段的**伪 URL** 前缀（design D6）。
#:
#: 片段没有网址，而 `SearchResult.url` 是必填的、`collector._dedupe()` 又按它去重，
#: 所以必须有一个能区分「同一文档的不同片段」的标识。用文件名会把一份文档的
#: 全部片段合成一条，用自增序号则跨文档会撞车。
#:
#: 常量放在本文件（叶子模块）而不是 `llm/kb/`：**生产方与消费方要共用同一个字面量** ——
#: `kb/tools.py` 拼它、`collector._source_for()` 认它。两处各写一份字符串，
#: 改一处就会让知识库片段被误判成网页资料。
KB_URL_PREFIX = "kb://"


def kb_url(*, kb_id: int, doc_id: int, chunk_index: int) -> str:
    """拼一条知识库片段的伪 URL（唯一的拼法，见 `KB_URL_PREFIX`）。"""
    return f"{KB_URL_PREFIX}{int(kb_id)}/{int(doc_id)}#{int(chunk_index)}"


def is_kb_url(url: str) -> bool:
    """这条 url 是不是知识库片段的伪 URL。"""
    return url.startswith(KB_URL_PREFIX)


#: 知识库检索工具的名字。
#:
#: 放在这里（而不是 `llm/kb/tools.py`）的理由与 `KB_URL_PREFIX` 相同：它有**两个
#: 消费方**且分属两层 —— `llm/kb/tools.py` 用它命名工具，
#: `llm/search/collector.py` 用它做白名单匹配。让采集器去 import `llm/kb/tools`
#: 会把知识库那一层（连带 `kb_service`）拖进检索层，而检索层在知识库关掉时
#: 也必须能独立工作。共用同一个字面量常数是这里唯一不会漂的写法。
#: 漏登记的后果是「命中数恒为 0 且不报错」，见 `test_search_collector_kb.py`。
KB_TOOL_NAME = "kb_search"


#: 落库的取材状态（`quizzes.search_state`）。三态的理由见 `SearchOutcome.search_state`。
SearchState = Literal["off", "degraded", "hit"]

#: 一次取材的结束原因。带 `_exhausted` 后缀的就是「撞到了某个上限」——
#: 上限名就在字符串里，所以日志与追溯字段不必各写一份（见 design D5）。
EndReason = Literal[
    "disabled",  # 压根没打算联网（开关关 + 没链接）
    "done",  # 正常收尾（模型不再要工具了）
    "no_tool_calls",  # 模型第一轮就没要工具
    "rounds_exhausted",  # 轮次上限
    "tool_calls_exhausted",  # 工具调用次数上限
    "budget_exhausted",  # 总时长上限
    "error",  # 循环内出现未预期的错误（已降级）
]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """一条资料。

    Attributes:
        title: 展示用标题。取不到时是空字符串 —— **不编造**。
        url: 来源地址。
        snippet: 注入 Prompt 的正文片段（已按上限截断、已清洗上游标记）。
        kind: `snippet`（检索摘要）或 `page`（整页正文）。
        source: `user`（用户自己给的链接）或 `web`（AI 检索到的）。
    """

    title: str
    url: str
    snippet: str
    kind: ResultKind = "snippet"
    source: ResultSource = "web"


@dataclass(frozen=True, slots=True)
class ReferenceCaps:
    """资料注入出题 Prompt 的体积上限。

    **值的唯一来源是 `Settings`**（经 `from_settings` 传入）；这里的默认值只是
    「直接构造一个实例」时的兜底，有单测钉住它与 `Settings` 的默认值一致。

    为什么必须有：实测单个网页正文可达 **74,801** 字符，而模型单次输出上限只有
    4096 token。不截断会把 Prompt 挤爆，而表现是「模型答非所问」——**不报错**（design D14）。
    """

    snippet_max_chars: int = 600
    page_max_chars: int = 6000
    total_max_chars: int = 12000
    #: 结构性兜底：最多注入几条。真实约束是 `total_max_chars`，条数只是防呆。
    max_items: int = 6

    @classmethod
    def from_settings(cls, settings: object) -> ReferenceCaps:
        """从 `Settings` 取值。

        故意的鸭子类型：`base.py` 是叶子模块，不该 import 配置（会把配置层拖进检索层）。
        """
        return cls(
            snippet_max_chars=getattr(settings, "search_snippet_max_chars", 600),
            page_max_chars=getattr(settings, "search_page_max_chars", 6000),
            total_max_chars=getattr(settings, "search_reference_max_chars", 12000),
            max_items=getattr(settings, "search_max_results", 5) + 1,
        )

    def limit_for(self, kind: ResultKind) -> int:
        """按资料形态取对应的单条上限。"""
        return self.page_max_chars if kind == "page" else self.snippet_max_chars


def truncate(text: str, limit: int, *, marker: str = " …（已截断）") -> str:
    """按字符数截断，并在截断处留下显式标记。

    留标记而不是静默截断：模型看到「半句话」时会自己脑补结尾，
    而看到标记就知道后面还有内容、不该臆测。
    """
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + marker


@dataclass(frozen=True, slots=True)
class KbScope:
    """本次出题要用的知识库作用域：**谁的**、**哪一个库**。

    两个字段缺一不可，而且它们对应**两层不同的隔离**（见 `llm/kb/store.py`）：
    `user_id` 决定落在哪个 Chroma collection（跨用户边界），
    `kb_id` 是检索时那个 `where` 过滤（同一用户跨库边界）。

    为什么不在 `SearchRequest` 里直接摊成两个 int 字段：它们总是一起出现、
    一起缺省，摊平之后 `SearchRequest(user_id=3)` 这种「只给了一半」的构造
    是合法的 —— 而它会让检索静默地跨库或跨用户。
    """

    user_id: int
    kb_id: int


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """一次取材请求。

    Attributes:
        query: 已清洗的用户输入（含链接时原样保留）。
        urls: 从输入里抽出的链接（去重、保序）。
        use_search: 用户这次的**意愿** —— 要不要让 AI 主动去网上搜。
            ⚠️ 它是意愿，不是能力：后端有没有配好检索是另一回事（见 `SearchProvider.can_search_web`）。
        max_results: 一次关键词检索要几条。上游把它列为**实例级**参数，所以由服务端定。
        kb: 本次要用的知识库（`None` = 不带库，行为与接入前逐位一致）。
            `kb_id` 的归属校验发生在**建任务之前**（design D13），所以走到这里
            的 scope 一定是本人且存在的。
    """

    query: str
    urls: tuple[str, ...] = ()
    use_search: bool = True
    max_results: int = 5
    kb: KbScope | None = None

    @property
    def has_urls(self) -> bool:
        return bool(self.urls)

    @property
    def has_kb(self) -> bool:
        """本次是否指定了知识库。"""
        return self.kb is not None

    @property
    def wants_external(self) -> bool:
        """这次是否需要访问外部网络。

        用户自己给的链接**必读**、不受 `use_search` 约束（design D4）——
        「我贴了链接却没被读」是这个产品最不能出现的失败。

        ⚠️ **不含知识库**：知识库是本地数据，不是外部网络。带库的请求算不算
        「要跑取材循环」由 `wants_grounding` 回答 —— 两者刻意分开，否则这个属性
        的名字就开始说谎，而它现在被 `agent` 用来决定「要不要一次工具都不调」。
        """
        return self.use_search or self.has_urls

    @property
    def wants_grounding(self) -> bool:
        """这次是否**有任何取材依据可取**（外部网络或自己的资料）。

        `agent.run_search_agent()` 用它决定要不要跑那个有界循环：
        不带库且不想联网的请求一轮模型都不该调（`end_reason="disabled"`）。
        """
        return self.wants_external or self.has_kb


@dataclass(frozen=True, slots=True)
class StepDescriptor:
    """进度条上一步的展示文案。前端直接渲染，不做判断。"""

    name: str
    detail: str


def build_initial_step(
    request: SearchRequest,
    *,
    can_search_web: bool,
    can_read_pages: bool,
    can_search_kb: bool = False,
) -> StepDescriptor:
    """按「输入里有没有链接 × 用户想不想搜 × 我有没有这个能力」决定第一步叫什么。

    ⚠️ 这里必须把**能力**一并算进去，否则会说出与实现不符的话：
    `NoopSearchProvider` 拿到「想联网」的请求时若显示「联网检索知识」，
    而它其实一次网络都不会碰 —— 那是红线上明令禁止的「文案与实现冲突」。

    优先级：链接 > 主动检索 > 知识库 > 理解输入。

    Args:
        can_search_kb: 这个 Provider 这次能不能检索知识库。
            ⚠️ 它**不做成 Provider 的能力位**（design D7）：知识库检索不取决于
            「配了哪个检索服务」，取决于「这次请求有没有带库」——
            同一个 Noop Provider，带库的请求该是 `True`、不带库的该是 `False`。
            所以由调用方按请求算好传进来，本函数保持纯函数
            （`base.py` 是叶子模块，不 import 配置）。
            默认 `False` 让既有的调用点行为逐位不变。
    """
    if request.has_urls and can_read_pages:
        count = len(request.urls)
        return StepDescriptor("读取你给的网页", f"正在读取 {count} 个链接")
    if request.use_search and can_search_web:
        return StepDescriptor("联网检索知识", "正在检索最新资料")
    if request.has_kb and can_search_kb:
        return StepDescriptor("检索你的知识库", "正在你的资料里查找相关内容")
    return StepDescriptor("理解你的输入", "正在解析你的学习需求")


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """一次取材的结果与过程追溯。

    Attributes:
        provider: Provider 名，用于日志与排查。
        step_name: 第一步的名字，由 Provider 在建 outcome 时盖上（= `initial_step().name`）。
        results: 拿到的资料；取不到时为空。
        rounds_used / tool_calls_used: 实际消耗的轮次与工具调用次数。
        end_reason: 结束原因；带 `_exhausted` 的就是撞到了某个上限。
    """

    provider: str
    step_name: str = "理解你的输入"
    results: tuple[SearchResult, ...] = ()
    rounds_used: int = 0
    tool_calls_used: int = 0
    end_reason: EndReason = "disabled"

    @property
    def hit_count(self) -> int:
        return len(self.results)

    @property
    def page_count(self) -> int:
        return sum(1 for item in self.results if item.kind == "page")

    @property
    def degraded(self) -> bool:
        """降级的**统一定义**：本轮取材结束后，没有任何可用资料。

        刻意做成派生属性而不是构造参数 —— 一个独立的 `degraded` 字段迟早会和
        `results` 打架（「标着降级却带着 3 条资料」），而那种不一致没人会发现（design D7）。
        """
        return not self.results

    @property
    def search_state(self) -> SearchState:
        """落库用的三态（`quizzes.search_state`，见 `sql/04_quiz_search_reference.sql`）。

        与 `degraded` 的区别：`degraded` 只说「有没有资料」（布尔），
        这里要区分「**压根没去取**」与「**去取了没取到**」——
        前者是配置问题（去看 `KNOWLEDGE_SEARCH_ENABLED`），后者是主题问题
        （换个说法或补一份资料）。两种三态混成一个布尔，排查时就分不开了。
        """
        # 资料的**有无**优先于结束原因：这样 `search_state == "hit"` 与 `not degraded`
        # 是同一个条件，两个派生值不可能各说各话。
        if self.results:
            return "hit"
        return "off" if self.end_reason == "disabled" else "degraded"
    @property
    def limit_hit(self) -> str | None:
        """触顶的上限名；没触顶则是 `None`。"""
        return self.end_reason if self.end_reason.endswith("_exhausted") else None

    def first_step(self, *, concept_count: int) -> StepDescriptor:
        """第一步的**最终**文案：名字不变，只把过程换成结果。

        Args:
            concept_count: 从输入中提炼出的核心概念数。取不到资料时用它说明「我们并非什么都没做」。
        """
        if self.hit_count == 0:
            if self.end_reason == "disabled":
                detail = f"已提炼 {concept_count} 个核心概念"
            else:
                # 真的去取过、但没取到 —— 如实说，不假装取到了。
                detail = f"未取到可用资料，已提炼 {concept_count} 个核心概念"
            return StepDescriptor(self.step_name, detail)

        detail = f"已完成 · 命中 {self.hit_count} 条资料"
        if self.page_count:
            detail += f"（其中整页 {self.page_count} 篇）"
        return StepDescriptor(self.step_name, detail)

    def as_reference(self, *, caps: ReferenceCaps | None = None) -> str:
        """拼成 Prompt 里的【参考资料】段落；无命中时返回空字符串。

        两处硬约束在这里落实：条数上限、以及**字符总量**上限（design D14）。
        字符总量是真正的护栏 —— 条数少不代表体积小（一页就是 7 万字符）。
        """
        if not self.results:
            return ""
        caps = caps or ReferenceCaps()
        lines: list[str] = []
        used = 0
        for index, item in enumerate(self.results, 1):
            if len(lines) >= caps.max_items:
                break
            block = reference_block(index, item)
            if used + len(block) > caps.total_max_chars:
                break
            lines.append(block)
            used += len(block)
        return "\n\n".join(lines)


def reference_block(index: int, item: SearchResult) -> str:
    """一条资料的 Prompt 段落。

    知识库片段**单独一种形态**（design D6）：它没有可点的网址，把
    `kb://7/12#3` 这种伪 URL 印给模型看只会让它以为那是个网页。
    改成印**文件名** —— 模型看到的是「来源：你的知识库《机器学习讲义.md》」，
    它的行为也随之不同：这是用户自己的材料，不是网上的东西。

    ⚠️ 非 kb 来源的输出格式**逐字未变**：既有 Prompt 契约测试是按原格式钉的
    （`test_search_prompt_contract.py`），改它就要连着改测试，而那条格式没有错。
    """
    if item.source == "kb":
        return f"[{index}] 来源：你的知识库《{item.title}》\n{item.snippet}"
    return f"[{index}] {item.title}\n{item.snippet}\n来源：{item.url}"


@runtime_checkable
class SearchProvider(Protocol):
    """检索 Provider 协议。

    实现方只需要三样东西：名字、一个「第一步叫什么」的方法、一个同步的 `gather`。
    同步而非异步，是因为出题链整体跑在后台线程里，异步只会平白多一层调度。
    """

    name: str

    #: 该 Provider 能不能主动联网检索（决定第一步有没有资格叫「联网检索知识」）
    can_search_web: bool

    #: 该 Provider 能不能按 URL 读整页
    can_read_pages: bool

    def initial_step(self, request: SearchRequest) -> StepDescriptor:
        """开工**之前**这一步叫什么。

        名字必须开工前就定下来（进度卡创建时就要展示），所以它不能依赖取材结果。
        """
        ...

    def gather(self, request: SearchRequest, *, on_progress: object = None) -> SearchOutcome:
        """取材。**不允许抛异常**：取不到就降级为空结果 + `degraded=True`，
        因为取材只是出题的增强项，不该把整个出题任务拖垮。

        Args:
            request: 取材请求。
            on_progress: 可选的进度回调（`ToolProgress -> None`）。做成**每次调用**的参数
                而不是构造参数，是因为进度要绑在任务上，而任务是在 Provider 构造之后
                才创建的 —— 写成构造参数就得引入一个可变的持有者来补挂，那更容易出错。
                回调是装饰性的：它抛异常不该中断取材。
        """
        ...
