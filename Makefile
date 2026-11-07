# 多模态通用智能体开发平台 · 一键命令
# 命令与 docs/reference/platform-spec-README.md §2 等价命令逐字一致。
# 本机 make 不可用时，直接执行注释中的等价 python3 命令。

.PHONY: demo test run eval

# DEMO_MODE=1 python3 scripts/demo.py
demo:
	DEMO_MODE=1 python3 scripts/demo.py

# DEMO_MODE=1 python3 -m pytest -q tests
test:
	DEMO_MODE=1 python3 -m pytest -q tests

# DEMO_MODE=1 python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
run:
	DEMO_MODE=1 python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# DEMO_MODE=1 python3 -m app.observability.evaluator
eval:
	DEMO_MODE=1 python3 -m app.observability.evaluator
