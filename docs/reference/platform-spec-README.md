多模态通用智能体开发平台



  面向求职作品集 / 实训的真实可运行项目：四模态统一接入 → 统一表征与多模态 RAG →
  Planner/Worker/Reflector 智能体编排 → 工具调用 → SSE 流式统一应答 → 轨迹回放与自动评测。



  
    验收红线：默认 `DEMO_MODE=1` 时零 API Key、零 GPU、零联网、零模型权重下载，
    即可端到端跑通全部链路。 生产模式的可选依赖全部用 `try/except ImportError` 包裹，
    缺失时自动降级，程序绝不崩溃。
  





  1. 架构



  ```
                      ┌────────────── 接入层 ──────────────┐
   text/image/audio/video → BaseModalityProcessor → ModalityChunk
     Pillow/numpy 归一   wave 元信息   cv2 抽帧(复用图像链路)
                      └──────────────────┬───────────────┘
                                         ▼
                      ┌────────────── 表征层 ──────────────┐
   BaseEncoder(Stub/API/Transformers) → VectorStore(Memory/Chroma, JSON 持久化)
   HybridRetriever = 稠密余弦 + 简化 BM25 + 重排 + 文本回退
                      └──────────────────┬───────────────┘
                                         ▼
                      ┌────────────── 编排层 ──────────────┐
   build_graph() → CompiledGraph.run() / stream_events() / resume()
     LangGraph StateGraph  |  纯 Python 等价状态机（同一接口、同一节点实现）
     Planner ──has_tool──▶ Worker ──continue──▶ Reflector ──done──▶ END
        ▲                    │                     │
        └────need_replan─────┘                     └──no_answer──▶ Planner
     最大步数保护 / 工具白名单 / 单工具超时 / 人工介入断点 / 状态可序列化
                      └──────────────────┬───────────────┘
                                         ▼
                      ┌────────────── 生成与观测 ──────────┐
   route_output + synthesize_answer(template | LLM API) → UnifiedResponse
   SSE: meta / step / token / human_required / done
   AgentTracer → data/traces.jsonl       Evaluator → 命中率/步数/延迟
                      └──────────────────┬───────────────┘
                                         ▼
   FastAPI: /health /v1/ingest /v1/chat /v1/trace/{id} /v1/eval /v1/tools
            同源托管 web/index.html（原生 JS，无需构建工具）
  ```



  分层原则：统一抽象层（`ModalityChunk` / `BaseEncoder` / `VectorStore` / `CompiledGraph`）
  屏蔽模态与后端差异，新增模态只实现 `process()`，切换后端只改配置，不需要改动编排与生成层。





  2. 快速启动（DEMO_MODE=1，推荐先跑这个）



  ```bash
  cd /workspace/multimodal-agent-platform
  python3 -m pip install -r requirements.txt   # 核心依赖；沙箱已预装可跳过

  make demo        # 一键端到端：四模态 ingest + Agent 轨迹打印 + API 冒烟
  make test        # pytest 全量测试
  make run         # 启动服务，浏览器打开 http://localhost:8000
  make eval        # 自带样例集评测报告
  ```



  等价命令：



  ```bash
  DEMO_MODE=1 python3 scripts/demo.py
  DEMO_MODE=1 python3 -m pytest -q tests
  DEMO_MODE=1 python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
  DEMO_MODE=1 python3 -m app.observability.evaluator
  ```



  `make demo` 不需要启动服务器：它直接调用组合根完成四模态入库与 Agent 运行，
  并用 `TestClient` 冒烟所有 API 端点。运行期产物写入 `data/`（自动创建）：
  `vector_index.json`（向量索引）、`traces.jsonl`（轨迹日志）。





  3. DEMO_MODE 说明（默认开启）



  
    
      
        能力
      
    

    
      
        DEMO_MODE=1（默认）
      
    

    
      
        DEMO_MODE=0（生产）
      
    
  

  
    
      
        编码器
      
    

    
      
        `StubEncoder`：哈希词频 + 字符分布，L2 归一化，确定性可复现
      
    

    
      
        `APIEncoder`（OpenAI 兼容 embeddings）或 `TransformersEncoder`（本地权重）
      
    
  

  
    
      
        Planner
      
    

    
      
        规则式（算术 / 时间 / 统计 / 检索关键字识别）
      
    

    
      
        LLM 输出 JSON 计划，解析失败回退规则式
      
    
  

  
    
      
        生成器
      
    

    
      
        模板式（结论 + 工具结果 + 引用证据 + 推理轨迹）
      
    

    
      
        LLM 对话补全，失败回退模板
      
    
  

  
    
      
        向量库
      
    

    
      
        `InMemoryVectorStore` + JSON 持久化
      
    

    
      
        可选 `ChromaVectorStore`
      
    
  

  
    
      
        图编排
      
    

    
      
        `PureStateMachine`（纯 Python 等价状态机）
      
    

    
      
        检测到 langgraph 时用真实 `StateGraph`，否则仍用等价状态机
      
    
  

  
    
      
        图像
      
    

    
      
        Pillow 归一 + numpy 颜色网格 / 感知指纹描述
      
    

    
      
        可选 OpenAI 兼容 VLM（`LLMClient.describe_image`）生成图像描述，失败回退 stub 特征
      
    
  

  
    
      
        音频
      
    

    
      
        `wave` 解析 WAV 元信息 + 确定性占位 ASR
      
    

    
      
        可选 Whisper 本地转写
      
    
  

  
    
      
        视频
      
    

    
      
        cv2 抽帧；不可解码时用内容哈希生成确定性合成帧
      
    

    
      
        同左（cv2 为核心依赖）
      
    
  



  强制约束：`DEMO_MODE=1` 时 `get_settings()` 无条件把 `llm_backend` / `encoder_backend` /
  `vector_backend` 锁定为 `template` / `stub` / `memory`，即使配置了 API Key 也不会发起任何网络请求。
  所有可选依赖（`langgraph`、`chromadb`、`whisper`、`openai`、`transformers`）在启动时只做
  `importlib.util.find_spec` 探测，缺失时走内置等价实现并标记 `fallback`。





  4. 生产模式配置（可选，非演示必需）



  ```bash
  cp .env.example .env
  # 编辑 .env：DEMO_MODE=0，填入任意 OpenAI 兼容端点与 Key
  DEMO_MODE=0 LLM_API_KEY=sk-xxx LLM_BASE_URL=https://your-endpoint/v1 
    LLM_MODEL=your-model python3 -m uvicorn app.main:app --port 8000
  ```



  可单独覆盖：`LLM_BACKEND=api|template`、`ENCODER_BACKEND=api|transformers|stub`、
  `VECTOR_BACKEND=chroma|memory`、`HUMAN_IN_LOOP=1`（人工介入断点）、
  `LLM_VISION_MODEL=`（图像 VLM 描述，留空复用 `LLM_MODEL`）。



  所有 LLM / Embedding 调用通过 httpx 直连 OpenAI 兼容端点，不依赖 `openai` SDK；
  未配置 Key 时自动保持 template/stub/memory，链路依旧可用。



  `transformers` 编码器仅从 `config/settings.yaml` 的 `encoder.local_model_path` 本地目录加载
  （`local_files_only=True`），不联网下载权重。



  `GET /health` 的 `components` 字段会逐一报告每个可选依赖是 `native` 还是 `fallback`，
  以及当前生效的图后端 / 编码器 / 向量库 / 生成器。





  5. API 一览（与前端调用完全一致，同源无跨域）



  
    
      
        方法
      
    

    
      
        路径
      
    

    
      
        说明
      
    
  

  
    
      
        GET
      
    

    
      
        `/health`
      
    

    
      
        健康状态、组件降级情况、索引切片数
      
    
  

  
    
      
        POST
      
    

    
      
        `/v1/ingest`
      
    

    
      
        `multipart/form-data`：`files`（可多传，按扩展名/MIME 识别模态）+ `text` + `source_tag`
      
    
  

  
    
      
        POST
      
    

    
      
        `/v1/chat`
      
    

    
      
        JSON `{query, session_id, stream, modalities}`；`stream=true` 返回 SSE
      
    
  

  
    
      
        GET
      
    

    
      
        `/v1/trace/{trace_id}`
      
    

    
      
        回放完整 JSONL 轨迹
      
    
  

  
    
      
        GET
      
    

    
      
        `/v1/tools`
      
    

    
      
        工具 JSON Schema 与生效白名单
      
    
  

  
    
      
        POST
      
    

    
      
        `/v1/eval`
      
    

    
      
        可选 `{"samples":[...]}`，不传则用 `samples/eval.jsonl`
      
    
  

  
    
      
        GET
      
    

    
      
        `/` 与 `/ui/index.html`
      
    

    
      
        单页 Web UI
      
    
  

  
    
      
        GET
      
    

    
      
        `/docs`
      
    

    
      
        FastAPI 自动文档
      
    
  



  SSE 事件类型：`meta` → `step`（每个节点）→ `token`（答案分片）→ `done`（完整 `UnifiedResponse`）；
  开启 `HUMAN_IN_LOOP` 时额外产生 `human_required`，可用 `graph.resume(state, "approved")` 继续。



  `UnifiedResponse` 字段：`answer` / `evidences[]`（证据块含 chunk_id、modality、snippet、score）/
  `tool_calls[]` / `tool_results[]` / `trace_id` / `steps` / `elapsed_ms` / `status` /
  `output_modality` / `demo_mode` / `graph_backend`。



  curl 示例：



  ```bash
  curl -X POST http://localhost:8000/v1/ingest -F 'text=平台采用 BM25 混合检索'
  curl -X POST http://localhost:8000/v1/chat 
    -H 'Content-Type: application/json' 
    -d '{"query":"计算 12*8 的结果","stream":false}'
  curl -N -X POST http://localhost:8000/v1/chat 
    -H 'Content-Type: application/json' 
    -d '{"query":"介绍一下平台","stream":true}'
  ```





  6. 目录结构



  ```
  multimodal-agent-platform/
  ├── app/
  │   ├── __init__.py            # 版本号
  │   ├── config.py              # YAML + 环境变量配置、可选依赖探测、路径解析
  │   ├── schemas.py             # 全局 Pydantic 契约（ModalityChunk / UnifiedResponse ...）
  │   ├── main.py                # FastAPI 应用 + 同源静态托管
  │   ├── modalities/            # 四模态接入
  │   │   ├── base.py            #   BaseModalityProcessor / RawInput / detect_modality
  │   │   ├── text.py            #   清洗 + 定长重叠切片
  │   │   ├── image.py           #   Pillow 归一 + numpy 颜色网格/感知指纹
  │   │   ├── audio.py           #   wave 元信息 + 确定性占位 ASR（可选 Whisper）
  │   │   └── video.py           #   cv2 抽帧 + 复用图像链路 + 时间戳
  │   ├── rag/
  │   │   ├── encoder.py         #   StubEncoder / APIEncoder / TransformersEncoder
  │   │   ├── store.py           #   VectorStore / InMemory(JSON) / Chroma / VectorIndex
  │   │   └── retriever.py       #   稠密余弦 + 简化 BM25 + 重排 + 文本回退
  │   ├── agent/
  │   │   ├── state.py           #   可序列化 AgentState（to_dict/from_dict）
  │   │   ├── tools.py           #   4 个内置工具 + Schema/校验/白名单/超时
  │   │   ├── nodes.py           #   Planner / Worker / Reflector
  │   │   └── graph.py           #   build_graph()/run()：LangGraph 或纯 Python 状态机
  │   ├── generation/router.py   #   模态路由、模板/LLM 生成器、SSE 格式化
  │   ├── observability/
  │   │   ├── tracer.py          #   JSONL 轨迹落盘与回放
  │   │   └── evaluator.py       #   命中率 / 平均步数 / 平均延迟
  │   └── api/routes.py          #   全部 REST 端点
  ├── web/index.html             # 原生 JS 单页控制台（无构建工具）
  ├── tests/                     # 四组 pytest：模态 / RAG / Agent / API
  ├── scripts/demo.py            # 一键端到端演示（自生成四种样例资源）
  ├── config/settings.yaml       # 主配置
  ├── samples/
  │   ├── knowledge.txt          # 内置检索知识（启动时自动灌入空索引）
  │   └── eval.jsonl             # 自带评测样例集
  ├── README.md  requirements.txt  .env.example  Makefile
  └── data/                      # 运行期生成：vector_index.json / traces.jsonl
  ```





  7. 关键设计决策与面试讲解要点



  统一抽象层而非四个模型堆砌：`ModalityChunk` 是唯一跨层契约；图像/视频帧被转成
  「颜色统计 + 感知指纹」的文本化描述，从而与文本共用同一个编码器与向量库，
  实现零模型成本下的跨模态检索。讲清楚「为什么这样能对齐」与「生产上换成 CLIP 的位置」。



  LangGraph 的等价降级：`build_graph()` 是唯一入口，`CompiledGraph` 是唯一接口；
  `PureStateMachine` 与 `LangGraphCompiled` 复用同一份节点函数与条件边规格
  （`EDGE_SPEC` / `CONDITIONAL_EDGES`），不是两套实现。这一步最能体现工程抽象能力。



  Agent 失控的四道防线：最大步数（`agent.max_steps`，超限强制进 Reflector 收敛）、
  工具白名单、单工具 `ThreadPoolExecutor` 超时、人工介入断点（`resume()` 状态恢复）。



  检索偏差治理：稠密 + BM25 加权融合 → 重排（子串命中加权、同源去重）→
  稠密无结果或全零时自动切换纯关键词文本回退，`last_debug.strategy` 可观测。



  确定性可复现：所有 DEMO 分支不使用 Python 内置 `hash()`（会随机化），
  一律 `hashlib`；视频降级帧用内容哈希做 numpy RNG 种子；配置版本化 + 全链路
  JSONL 轨迹，便于答辩复盘。



  STAR 量化叙事示例：「在没有 GPU 与 API 预算的约束下，用统一抽象层把 4 种模态
  接入、混合检索、Agent 编排、工具调用与 SSE 应答串成一条可运行链路；
  自带 8 条评测样例输出命中率/平均步数/平均延迟；所有可选依赖缺失时自动降级，
  `pytest` 全量通过，`make demo` 一键复现。」



  可扩展点（答辩加分区）：`BaseEncoder` 换 CLIP/Qwen2-VL、`VectorStore` 换 Milvus、
  `BaseTool` 注册外部 API、`CompiledGraph` 加记忆/多智能体节点、生成层接 TTS/文生图。





  8. 已知限制



  DEMO 模式使用确定性 stub 特征与模板答案，语义质量不等价于真实多模态大模型，
  指标（命中率等）只用于链路正确性与回归验证，不代表业务准确率。



  SSE 的 `token` 事件由最终答案按定长切片模拟；生产模式 LLM 的真实增量输出接口
  （`LLMClient.chat_stream`）已提供，但未挂到主应答路径上。



  图像/音频/视频在 DEMO 模式下生成的是描述性文本证据，不做真实图像生成、TTS 或
  ASR；音频仅解析 PCM WAV 容器，视频抽帧在容器不可解码时降级为确定性合成帧。



  内存向量库是暴力余弦扫描，适合万级以下切片的演示；生产建议切换 Chroma / Milvus。



  `samples/eval.jsonl` 为自建小型基准（8 条），不含公开榜（MMBench/SEED）评测。



  未实现多租户、鉴权、会话持久化与并发写入锁；`/v1/chat` 的流式请求与入库请求
  共享进程内索引，适合单机演示。
