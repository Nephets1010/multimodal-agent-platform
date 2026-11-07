"""全局数据契约（Pydantic v2）与统一异常体系。

本模块是依赖图的最底层之一：**不得 import 任何 ``app.*`` 业务模块**。
所有 REST 响应、SSE ``data``、JSONL 轨迹、评测样例都以此处的模型为准。

设计要点（对应 docs/ARCHITECTURE.md §3.1 与 PRD §4）：
* ``UnifiedResponse`` 恰好 11 字段，全局唯一构造点是
  :func:`app.generation.router.build_unified_response`。
* ``ModalityChunk`` 恰好 5 字段，是四模态接入层唯一跨层载体。
* ``ToolResult.error`` 恒存在（成功时为 ``None``），前端直接读取。
* ``ChatRequest.modalities`` 用 ``default_factory=list``，缺省与 ``[]`` 等价。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #


class ModalityType(str, Enum):
    """四模态取值域。"""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class Status(str, Enum):
    """链路状态（Q4）。``/health.status`` 与 ``UnifiedResponse.status`` 共用。"""

    OK = "ok"
    DEGRADED = "degraded"
    ERROR = "error"


class OutputModality(str, Enum):
    """输出模态（Q4）。DEMO 下恒为 ``text``。"""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    MIXED = "mixed"


class GraphBackend(str, Enum):
    """生效图后端（Q4）。探测结果 native/fallback 与本枚举是两条独立数据流。"""

    PURE = "pure"
    LANGGRAPH = "langgraph"


# --------------------------------------------------------------------------- #
# 基础契约模型
# --------------------------------------------------------------------------- #


class _ContractModel(BaseModel):
    """所有契约模型的公共基类：忽略未知字段，禁止 ``extra="allow"`` 静默改结构。"""

    model_config = ConfigDict(extra="ignore")


class ModalityChunk(_ContractModel):
    """四模态接入层统一产物，**恰好 5 字段**（PRD §1.2-3，禁止删改/重命名）。"""

    chunk_id: str
    source_id: str
    modality: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RawInput(_ContractModel):
    """接入层内部输入。

    ``content`` 为原始字节；``text`` 对文本模态是粘贴的正文，对视频模态
    作为「已落盘的临时文件路径提示」使用（由 ``api/routes.py`` 注入），
    从而使得 ``VideoProcessor.process`` 保持「只读、不写文件」的纯函数语义。
    """

    name: str
    content: bytes = b""
    mime: str = ""
    source_tag: str = "webui"
    text: str | None = None


class IngestChunkItem(_ContractModel):
    """``POST /v1/ingest`` 响应 ``chunks[]`` 元素（Q2）。"""

    chunk_id: str
    source_id: str
    modality: str
    snippet: str


class IngestResponse(_ContractModel):
    """``POST /v1/ingest`` 响应（Q2）：顶层仅这两个字段。"""

    chunks: list[IngestChunkItem] = Field(default_factory=list)
    total: int = 0


class ChatRequest(_ContractModel):
    """``POST /v1/chat`` 请求体（Q4）。"""

    query: str
    session_id: str = "default"
    stream: bool = True
    modalities: list[str] = Field(default_factory=list)


class Evidence(_ContractModel):
    """引用证据（Q5）：必需 4 字段，附加 ``source_id``。"""

    chunk_id: str
    modality: str
    snippet: str
    score: float
    source_id: str | None = None


class ToolCall(_ContractModel):
    """工具调用记录（Q6）。"""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: str | None = None


class ToolResult(_ContractModel):
    """工具执行结果（Q6）：**恒含 5 字段**，``error`` 成功时为 ``None``。"""

    name: str
    ok: bool
    elapsed_ms: float = 0.0
    output: Any = None
    error: str | None = None


class ToolDescriptor(_ContractModel):
    """``GET /v1/tools`` 的 ``tools[]`` 元素（Q8）。"""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class UnifiedResponse(_ContractModel):
    """统一应答，**恰好 11 字段**（PRD §4.3），非流式与 SSE ``done`` 共用。"""

    answer: str
    evidences: list[Evidence] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    trace_id: str
    steps: int = 0
    elapsed_ms: float = 0.0
    status: Status = Status.OK
    output_modality: OutputModality = OutputModality.TEXT
    demo_mode: bool = True
    graph_backend: GraphBackend = GraphBackend.PURE


# --------------------------------------------------------------------------- #
# SSE 事件 data 契约（前端 parseFrame 逐行 JSON.parse）
# --------------------------------------------------------------------------- #


class MetaEventData(_ContractModel):
    trace_id: str
    backend: str


class StepEventData(_ContractModel):
    steps: int
    node: str
    next_node: str
    status: str
    last_observation: str = ""


class TokenEventData(_ContractModel):
    delta: str


class HumanRequiredEventData(_ContractModel):
    prompt: str


# --------------------------------------------------------------------------- #
# 健康 / 工具 / 轨迹 / 评测
# --------------------------------------------------------------------------- #


class HealthComponents(_ContractModel):
    """``/health.components``，前端逐一读取 **11 项**（Q1）。"""

    graph: str = "pure"
    encoder: str = "stub"
    vector: str = "memory"
    llm: str = "template"
    index_chunks: int = 0
    langgraph: str = "fallback"
    chromadb: str = "fallback"
    whisper: str = "fallback"
    cv2: str = "fallback"
    transformers: str = "fallback"
    openai: str = "fallback"


class HealthResponse(_ContractModel):
    """``GET /health``（Q1）：顶层 ``index_chunks`` 与 ``components.index_chunks`` 同值。

    ``configured_backends`` 是可选附加字段：**仅生产模式**输出配置声明的后端值，
    用于在发生降级时对照 ``components`` 里的实际生效值；DEMO 下配置值==生效值，
    该字段不输出，保证 ``/health`` 响应与前端既有消费路径完全不变。
    """

    demo_mode: bool
    components: HealthComponents
    status: Status = Status.OK
    version: str = "1.0.0"
    index_chunks: int = 0
    configured_backends: dict[str, str] | None = None


class ToolsResponse(_ContractModel):
    """``GET /v1/tools``（Q8）。"""

    tools: list[ToolDescriptor] = Field(default_factory=list)
    whitelist: list[str] = Field(default_factory=list)
    max_steps: int = 8
    tool_timeout_seconds: float = 3.0


class TraceEvent(_ContractModel):
    """JSONL 轨迹每行一条；前端消费 ``event``/``node``/``steps``/``status``。"""

    ts: str
    trace_id: str
    session_id: str = "default"
    event: str
    node: str = ""
    steps: int = 0
    status: str = "ok"
    elapsed_ms: float = 0.0
    state_snapshot: dict[str, Any] = Field(default_factory=dict)


class TraceResponse(_ContractModel):
    """``GET /v1/trace/{trace_id}``（Q7）：不存在时 ``events=[]``, ``count=0`` + HTTP 200。"""

    events: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class EvalSample(_ContractModel):
    """``samples/eval.jsonl`` 每行 schema（Q9），四键全部存在。

    ``expected_answer_contains`` 仅为样例元数据，**不参与命中判定**。
    """

    query: str
    expected_keywords: list[str] = Field(default_factory=list)
    expected_tools: list[str] = Field(default_factory=list)
    expected_answer_contains: list[str] = Field(default_factory=list)


class EvalRequest(_ContractModel):
    """``POST /v1/eval`` 请求（Q9）：``samples`` 是**数组**，前端发 ``{}``。"""

    samples: list[EvalSample] | None = None


class EvalDetail(_ContractModel):
    """``details[]`` 元素（Q9）：``actual_tools`` 必须是 list（前端 ``.join(",")``）。"""

    hit: bool
    query: str
    actual_tools: list[str] = Field(default_factory=list)
    steps: int = 0
    latency_ms: float = 0.0


class EvalResponse(_ContractModel):
    """``POST /v1/eval`` 响应（Q9）：``samples`` 是**数量数字**，同名不同义保持。"""

    hit_rate: float = 0.0
    tool_hit_rate: float = 0.0
    avg_steps: float = 0.0
    avg_latency_ms: float = 0.0
    samples: int = 0
    details: list[EvalDetail] = Field(default_factory=list)


#: ``CompiledGraph.stream_events()`` 产出的帧：``(event_name, data_dict)``。
#: 真正的字节串由 :func:`app.generation.router.format_sse` 统一生成。
SSEFrame: TypeAlias = tuple[str, dict[str, Any]]


# --------------------------------------------------------------------------- #
# 统一异常体系（同放本模块，避免新增 app 级模块）
# --------------------------------------------------------------------------- #


class PlatformError(Exception):
    """平台领域异常基类，映射为 ``{"detail": ...}`` + ``http_status``。"""

    code: str = "platform_error"
    http_status: int = 500

    def __init__(
        self,
        detail: str = "内部错误，请查看服务端日志",
        *,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status


class ConfigError(PlatformError):
    """配置键名／取值域／路径非法（启动期）。"""

    code = "config_error"
    http_status = 500


class IngestError(PlatformError):
    """扩展名不在白名单、超限、文件名非法、参数校验失败。"""

    code = "ingest_error"
    http_status = 400


class ModalityError(PlatformError):
    """单文件解析失败；由 ingest 捕获为「跳过该文件 + warning」并降级。"""

    code = "modality_error"
    http_status = 400


class ToolError(PlatformError):
    """未注册工具／参数校验失败；转 ``ToolResult(ok=False)``，不抛到 HTTP 层。"""

    code = "tool_error"
    http_status = 200


class ToolTimeoutError(ToolError):
    """``future.result`` 超时；转 ``ToolResult(ok=False, error="tool timeout")``。"""

    code = "tool_timeout"


class IndexCorruptedError(PlatformError):
    """``vector_index.json`` 损坏；清空重建 + warning，不抛到 HTTP 层。"""

    code = "index_corrupted"
    http_status = 200


__all__ = [
    "ModalityType",
    "Status",
    "OutputModality",
    "GraphBackend",
    "ModalityChunk",
    "RawInput",
    "IngestChunkItem",
    "IngestResponse",
    "ChatRequest",
    "Evidence",
    "ToolCall",
    "ToolResult",
    "ToolDescriptor",
    "UnifiedResponse",
    "MetaEventData",
    "StepEventData",
    "TokenEventData",
    "HumanRequiredEventData",
    "HealthComponents",
    "HealthResponse",
    "ToolsResponse",
    "TraceEvent",
    "TraceResponse",
    "EvalSample",
    "EvalRequest",
    "EvalDetail",
    "EvalResponse",
    "SSEFrame",
    "PlatformError",
    "ConfigError",
    "IngestError",
    "ModalityError",
    "ToolError",
    "ToolTimeoutError",
    "IndexCorruptedError",
]
