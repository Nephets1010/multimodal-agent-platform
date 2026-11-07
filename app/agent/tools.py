"""4 个白名单工具 + 受限 AST 计算器 + 自写参数校验 + 线程池超时护栏。

禁止事项：``eval`` / ``exec`` / 内置 ``hash()`` / ``jsonschema`` / 顶层硬 import 可选依赖。
工具失败一律转 ``ToolResult(ok=False)``，**不抛到 HTTP 层**，链路继续。
"""

from __future__ import annotations

import ast
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.schemas import ToolDescriptor, ToolResult

if TYPE_CHECKING:
    from app.config import Settings
    from app.rag.retriever import HybridRetriever

# --------------------------------------------------------------------------- #
# 受限 AST 计算器（禁止 eval / exec）
# --------------------------------------------------------------------------- #

_ALLOWED_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_ALLOWED_UNARY_OPS = (ast.UAdd, ast.USub)
_MAX_AST_DEPTH = 24
_MAX_POW_EXPONENT = 64
_MAX_ABS_VALUE = 1.0e15
_MAX_EXPR_LENGTH = 256
_WORD_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def _eval_node(node: ast.AST, depth: int = 0) -> float | int:
    """只允许 Expression / BinOp(四则) / UnaryOp(±) / Constant(int|float)。"""
    if depth > _MAX_AST_DEPTH:
        raise ValueError("表达式嵌套过深")

    if isinstance(node, ast.Expression):
        return _eval_node(node.body, depth + 1)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("仅允许数字字面量")
        if abs(node.value) > _MAX_ABS_VALUE:
            raise ValueError("数字字面量过大")
        return node.value

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY_OPS):
        operand = _eval_node(node.operand, depth + 1)
        return +operand if isinstance(node.op, ast.UAdd) else -operand

    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BIN_OPS):
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        op = node.op
        if isinstance(op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError("除零")
        if isinstance(op, ast.Pow):
            if abs(right) > _MAX_POW_EXPONENT or abs(left) > 1.0e6:
                raise ValueError("幂运算超出限制")
            result: float | int = left**right
        elif isinstance(op, ast.Add):
            result = left + right
        elif isinstance(op, ast.Sub):
            result = left - right
        elif isinstance(op, ast.Mult):
            result = left * right
        elif isinstance(op, ast.Div):
            result = left / right
        elif isinstance(op, ast.FloorDiv):
            result = left // right
        else:
            result = left % right
        if abs(result) > _MAX_ABS_VALUE:
            raise ValueError("运算结果过大")
        return result

    # Call / Attribute / Name / Subscript / Import / Lambda / Compare / BitOp 全部拒绝
    raise ValueError(f"不允许的表达式节点 {type(node).__name__}")


def safe_calculate(expression: str) -> float | int:
    """受限 AST 求值入口；任何非法语法都抛异常，由 ``invoke`` 转结构化失败。"""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("表达式为空")
    if len(expression) > _MAX_EXPR_LENGTH:
        raise ValueError("表达式过长")
    tree = ast.parse(expression.strip(), mode="eval")
    return _eval_node(tree)


# --------------------------------------------------------------------------- #
# 自写 JSON Schema 参数校验（禁止 import jsonschema）
# --------------------------------------------------------------------------- #


def _type_matches(expected: str, value: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> str | None:
    """校验 ``required`` / 类型 / 未知键；返回错误说明或 ``None``。"""
    if not isinstance(arguments, dict):
        return "arguments 必须是对象"
    properties = schema.get("properties", {}) or {}
    for required in schema.get("required", []) or []:
        if required not in arguments:
            return f"缺少必需参数 {required}"
    for key, value in arguments.items():
        if key not in properties:
            return f"未知参数 {key}"
        expected = (properties.get(key) or {}).get("type")
        if expected and not _type_matches(str(expected), value):
            return f"参数 {key} 类型不符，期望 {expected}"
    return None


# --------------------------------------------------------------------------- #
# 4 个内置工具
# --------------------------------------------------------------------------- #


class BaseTool(ABC):
    """工具统一接口。"""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:
        raise NotImplementedError


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "受限 AST 安全四则运算（禁 eval/exec、禁函数调用与属性访问）"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "仅含数字与 + - * / % ** 的表达式"}
        },
        "required": ["expression"],
    }

    def run(self, **kwargs: Any) -> Any:
        return safe_calculate(str(kwargs.get("expression", "")))


class CurrentTimeTool(BaseTool):
    name = "current_time"
    description = "返回当前 UTC 与本地时间（ISO8601），唯一非确定性来源"
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs: Any) -> Any:
        utc = datetime.now(timezone.utc)
        local = datetime.now().astimezone()
        return {
            "utc": utc.isoformat(),
            "local": local.isoformat(),
            "timezone": str(local.tzinfo),
            "epoch": time.time(),
        }


class KnowledgeSearchTool(BaseTool):
    name = "knowledge_search"
    description = "调用混合检索器（稠密余弦 + BM25 + 重排 + 关键词回退）"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索问题"},
            "top_k": {"type": "integer", "description": "返回证据条数"},
        },
        "required": ["query"],
    }

    def __init__(self, retriever: "HybridRetriever") -> None:
        self._retriever = retriever

    def run(self, **kwargs: Any) -> Any:
        query = str(kwargs.get("query", ""))
        top_k = int(kwargs.get("top_k", 5) or 5)
        evidences, debug = self._retriever.retrieve(query, [], top_k)
        return {
            "query": query,
            "count": len(evidences),
            "strategy": debug.get("strategy", "empty"),
            "evidences": [item.model_dump(mode="json") for item in evidences],
        }


class TextStatsTool(BaseTool):
    name = "text_stats"
    description = "字数统计与抽取式摘要"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "待统计文本"}},
        "required": ["text"],
    }

    def run(self, **kwargs: Any) -> Any:
        text = str(kwargs.get("text", "") or "")
        tokens = _WORD_RE.findall(text)
        sentences = [part.strip() for part in re.split(r"[。！？\n.!?]", text) if part.strip()]
        summary = " ".join(sentences[:2])[:120]
        return {
            "char_count": len(text),
            "token_count": len(tokens),
            "sentence_count": len(sentences),
            "summary": summary,
        }


def build_default_tools(
    retriever: "HybridRetriever", settings: "Settings"
) -> list[BaseTool]:
    """构造 4 个内置工具（唯一注册来源）。"""
    return [
        CalculatorTool(),
        CurrentTimeTool(),
        KnowledgeSearchTool(retriever),
        TextStatsTool(),
    ]


# --------------------------------------------------------------------------- #
# 注册表：白名单 + 参数校验 + ThreadPoolExecutor 超时
# --------------------------------------------------------------------------- #


class ToolRegistry:
    """只注册 4 个工具；``invoke`` 恒返回 5 字段 ``ToolResult``。"""

    def __init__(self, retriever: "HybridRetriever", settings: "Settings") -> None:
        self._settings = settings
        self._timeout = float(settings.agent.tool_timeout_seconds)
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._tools: dict[str, BaseTool] = {}
        for tool in build_default_tools(retriever, settings):
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[str(tool.name)] = tool

    def whitelist(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                name=tool.name,
                description=tool.description,
                parameters=dict(tool.parameters),
            )
            for tool in (self._tools[key] for key in sorted(self._tools))
        ]

    def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """白名单 → 自写校验 → 线程池超时 → 结构化结果（链路永不中断）。"""
        started = time.perf_counter()
        tool = self._tools.get(str(name))
        if tool is None:
            return ToolResult(
                name=str(name),
                ok=False,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                output=None,
                error="tool not in whitelist",
            )

        problem = validate_arguments(tool.parameters, arguments)
        if problem is not None:
            return ToolResult(
                name=str(name),
                ok=False,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                output=None,
                error=f"参数校验失败：{problem}",
            )

        try:
            future = self._pool.submit(tool.run, **arguments)
            output = future.result(timeout=self._timeout)
            return ToolResult(
                name=str(name),
                ok=True,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                output=output,
                error=None,
            )
        except FuturesTimeout:
            return ToolResult(
                name=str(name),
                ok=False,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                output=None,
                error=f"tool timeout after {self._timeout}s",
            )
        except Exception as exc:
            return ToolResult(
                name=str(name),
                ok=False,
                elapsed_ms=(time.perf_counter() - started) * 1000.0,
                output=None,
                error=f"{type(exc).__name__}: {exc}",
            )

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


__all__ = [
    "BaseTool",
    "CalculatorTool",
    "CurrentTimeTool",
    "KnowledgeSearchTool",
    "TextStatsTool",
    "ToolRegistry",
    "build_default_tools",
    "safe_calculate",
    "validate_arguments",
]
