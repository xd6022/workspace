---
topic: "LangGraph"
version: 1
concepts: 20
relations: 27
created: 2026-05-09
confidence: 0.85
ir: "[[LangGraph.knowledge.json]]"
---

# LangGraph

## 一句话总结

LangGraph 是一个低层级的 Agent 编排框架和运行时，用有向图建模长时间运行、有状态的 AI Agent 工作流。它独立于 [[LangChain]] 但与之深度协作，提供 Durable Execution 和 Human-in-the-Loop 等核心特性。

## 核心概念

LangGraph 由以下内部抽象组成：

| 概念 | 角色 | 说明 |
|------|------|------|
| [[State\|状态]] | 数据载体 | 共享数据结构，贯穿所有节点，通过 [[Reducer]] 控制字段更新策略 |
| [[Nodes\|节点]] | 执行单元 | 接收 State 执行业务逻辑，返回部分更新 |
| [[Edges\|边]] | 路由控制 | 根据 State 动态或静态决定下一个 [[Nodes\|Node]] |
| [[Reducer\|合并器]] | 合并策略 | 控制 State 各字段的更新方式：覆盖 / 追加 / 自定义 |
| [[Checkpointer\|检查点]] | 持久化引擎 | 每步保存 State 快照，是 [[Durable Execution]] 的存储基础 |
| [[Thread\|线程]] | 实例标识 | 通过 thread_id 隔离不同工作流的 checkpoint 链 |
| [[Task]] | 副作用容器 | @task 包裹 API 调用等非确定性操作，恢复时读缓存 |
| [[StateGraph]] | 图构建器 | 核心 API 入口，`add_node → add_edge → compile` |
| [[Functional API]] | 替代范式 | 单函数定义 Agent，内部自动编译为 StateGraph |

## 工作原理

### [[Durable Execution]] — LangGraph 最核心特性

| 要素 | 作用 |
|------|------|
| [[Checkpointer]] | 每步自动持久化 State 快照 |
| [[Task]] | 包裹副作用操作，恢复时回放缓存结果而非重复执行 |
| [[Thread]] | 隔离不同实例的 checkpoint 历史 |

> 恢复机制：从最后 checkpoint 重放到中断点，而非从中断行继续。所有副作用必须包在 [[Task]] 中。

三种模式：`exit`（最快）→ `async`（平衡）→ `sync`（最安全）

### [[Super-Step]] 调度模型 —— 继承自 [[Pregel]]

```
┌──────────┐  message  ┌──────────┐
│  Node A  │ ────────→ │  Node B  │
│ inactive │           │  active  │
└──────────┘           └────┬─────┘
                            │ update State → Reducer
                            ▼
                       ┌──────────┐
                       │  Node C  │
                       │  active  │
                       └──────────┘
```

- 所有节点初始 `inactive`，收到消息变 `active`
- 同一 [[Super-Step]] 内节点并行，步间串行
- 全 inactive 且无消息在途 → 图终止

### [[Human-in-the-Loop]]

- `interrupt()` — 任意节点暂停，等待人工介入
- `Command(resume=...)` — 人工修改 State 后继续执行
- 审批、校验、关键决策的一等公民原语

## 应用场景

| 场景 | 流程 |
|------|------|
| 🤖 智能 Agent | LLM 推理 → 工具调用 → 条件路由 → 循环 |
| 🔁 多步流水线 | 检索 → 排序 → 生成 → 验证 → 重试 |
| 👥 多 Agent 协作 | 子 Agent 并行 → 汇总 → 决策 → 分发 |
| 📋 审批流 | AI 草案 → 人工审核 → 修改 → 发布 |
| ⏳ 长时任务 | 持续数小时/天，中断后由 [[Durable Execution]] 自动恢复 |

## 优缺点

### ✅ 优点

- 低层级高灵活：不预设 Agent 架构
- [[Durable Execution]]：崩溃/超时不丢进度
- [[Human-in-the-Loop]] 一等公民：内置原语
- 与 [[LangSmith]] 深度集成：可视化追踪 + 评估
- 独立于 [[LangChain]]：可单独使用
- 双 API：[[StateGraph]] + [[Functional API]]
- 生产验证：Klarna、Uber、J.P. Morgan 已上线

### ❌ 缺点

- 概念量大：[[State]] / [[Reducer]] / [[Checkpointer]] / [[Task]] / [[Thread]] 学习曲线陡
- 简单场景杀鸡用牛刀：[[LangChain]] `create_agent` 更合适
- 调试心智负担：需理解 [[Super-Step]]、消息传递、重放机制
- 生态习惯绑定 [[LangChain]] + [[LangSmith]]
- TS 版功能滞后 Python 版
- Pydantic State 有额外校验开销

## 相关概念

| 概念 | 关系 | 方向 | 强度 |
|------|------|------|------|
| [[LangChain]] | 使用 LangGraph 作为 Agent 运行时 | LangChain → LangGraph | 0.70 |
| [[Deep Agents]] | 在 LangGraph 之上封装高层能力 | Deep Agents → LangGraph | 0.75 |
| [[LangSmith]] | 追踪、评估和部署 LangGraph | LangSmith → LangGraph | 0.60 |
| [[Pregel]] | 图执行模型的灵感来源 | LangGraph ← Pregel | 0.30 |
| [[Apache Beam]] | 流式 API 设计的灵感来源 | LangGraph ← Beam | 0.20 |
| [[CrewAI]] | 竞品，角色扮演式多 Agent | 双向竞争 | 0.50 |
| [[AutoGen]] | 竞品，对话式多 Agent | 双向竞争 | 0.50 |

## 我的理解

把 LangGraph 比作 **智能体工厂的流水线调度系统**：

| 类比 | 对应概念 | 含义 |
|------|----------|------|
| 🏭 产品 | [[State]] | 流水线上流转的数据 |
| 👷 工位 | [[Nodes]] | 每个工序（调LLM/搜资料/写文件） |
| 🏗️ 传送带 | [[Edges]] | 决定产品下一站去哪 |
| 📸 监控 | [[Checkpointer]] | 每步拍照，出问题从照片恢复 |
| 🏷️ 防重 | [[Task]] | 标记外部操作，恢复时跳过 |
| ⏸️ 暂停 | [[Human-in-the-Loop]] | 关键决策让人拍板 |

## 待研究问题

1. [[Super-Step]] 并行机制：底层并发模型是 asyncio 还是线程池？
2. [[StateGraph]] vs [[Functional API]] 性能差异？
3. [[Checkpointer]] 后端对比：MemorySaver vs PostgresSaver vs SqliteSaver？
4. Streaming 模式：token-level / node-level / custom 实现细节？
5. 多 Agent 通信：subgraph vs 直接消息传递适用场景？
6. LangGraph.js vs Python 版功能差距？
7. [[Deep Agents]] vs LangGraph 的迁移边界？

---

*关联笔记：[[LangChain]] · [[LangSmith]] · [[Deep Agents]] · [[Pregel]] · [[Apache Beam]] · [[CrewAI]] · [[AutoGen]] · [[Durable Execution]] · [[Human-in-the-Loop]]*

*知识结构：[[LangGraph.knowledge.json]]*
