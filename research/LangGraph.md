---
tags:
  - ai
  - agent
  - orchestration
  - llm
  - framework
created: 2026-05-09
topic: "LangGraph"
status: done
concepts: 20
relations: 22
knowledge_graph: "[[LangGraph.knowledge.json]]"
---

# LangGraph

## 一句话总结

LangGraph 是一个低层级的 Agent 编排框架和运行时，用「图」来建模和管理长时间运行、有状态的 AI Agent 工作流。它独立于 [[LangChain]]，但与之深度协作。

## 核心概念

LangGraph 内部由以下核心抽象组成：

| 概念 | 角色 | 说明 |
|------|------|------|
| **State** | 数据载体 | 共享数据结构，贯穿所有节点，用 `TypedDict` 或 Pydantic 定义 |
| **Nodes** | 执行单元 | 接收当前 State、执行业务逻辑、返回 State 更新 |
| **Edges** | 路由控制 | 根据 State 决定下一个 Node，支持固定跳转 + 条件分支 |
| **Reducer** | 合并策略 | 定义每个 State 字段如何被更新（覆盖 / 追加 / 自定义） |
| **Checkpointer** | 持久化引擎 | 每步保存 State 快照，是 [[Durable Execution]] 的基石 |
| **Thread** | 实例标识 | 通过 `thread_id` 关联一次工作流执行的完整状态链 |
| **Task** | 副作用容器 | 用 `@task` 包裹非确定性操作（API 请求、随机数），恢复时读缓存 |
| **Super-Step** | 调度粒度 | 同一 super-step 内节点可并行，不同 super-step 串行 |
| **StateGraph** | 图构建器 | Graph API 核心类，`add_node` → `add_edge` → `compile` |
| **Functional API** | 替代范式 | 单函数定义 Agent，内部自动编译为图 |

## 工作原理

### 执行模型 —— 继承自 [[Pregel]] 的消息传递

```
┌──────────┐   message   ┌──────────┐
│  Node A  │ ──────────→ │  Node B  │
│ inactive │             │  active  │
└──────────┘             └────┬─────┘
                              │ update State
                              ▼
                         ┌──────────┐
                         │  Node C  │
                         │  active  │
                         └──────────┘
```

1. 所有节点初始 `inactive`
2. 收到消息（State 更新）→ 变为 `active` → 执行
3. 以 **Super-Step** 为单位批处理：同一步内并行，步间串行
4. 所有节点 inactive + 无消息在途 → 图终止

### State 流转

```
输入 State → Node(读部分字段) → Node(返回更新) → Reducer(合并) → 新 State
```

- 默认 reducer = 覆盖；消息列表常用 `operator.add` 追加
- 支持 Input / Output / Internal / Private 四种 Schema 分层

### [[Durable Execution]] —— LangGraph 的杀手特性

| 要素 | 作用 |
|------|------|
| **Checkpointer** | 每步自动保存 State 快照 |
| **Task** | 包裹副作用，恢复时回放缓存结果 |
| **Thread** | 隔离不同工作流实例的 checkpoint 链 |

> ⚠️ 恢复不是「从中断行接着跑」，而是**从最后 checkpoint 重放到中断点**。因此所有副作用必须包在 Task 里。

三种持久化模式：`exit`（快但不可恢复崩溃）→ `async`（平衡）→ `sync`（最安全）

### [[Human-in-the-Loop]]

- `interrupt()` → 任意节点暂停，等待人工
- `Command(resume=...)` → 人工修改 State 后继续
- 审批、审核、关键决策场景的一等公民支持

## 应用场景

| 场景 | 典型流程 |
|------|----------|
| 🤖 智能 Agent | LLM 推理 → 工具调用 → 判断结果 → 循环 (ReAct) |
| 🔁 多步流水线 | RAG 检索 → 重排序 → 生成 → 验证 → 重试 |
| 👥 多 Agent 协作 | 子 Agent 并行执行 → 汇总 → 决策 → 分发 |
| 📋 审批流 | AI 草案 → 人工审核 → 修改 → 发布 |
| ⏳ 长时任务 | 持续数小时/天，中断后自动恢复 |

## 优缺点

### ✅ 优点

- **低层级高灵活**：不预设 Agent 架构，完全可控
- **[[Durable Execution]]**：崩溃/超时不丢进度，断点续跑
- **[[Human-in-the-Loop]] 一等公民**：不是事后改造，是内置原语
- **短期 + 长期记忆**：Thread 工作记忆 + 跨会话持久化
- **与 [[LangSmith]] 深度集成**：每步可视化、可追踪、可评估
- **独立于 [[LangChain]]**：可单独使用，无强制绑定
- **双 API**：Graph API（显式工作流） + Functional API（简洁 Agent）
- **生产验证**：Klarna、Uber、J.P. Morgan 已上线

### ❌ 缺点

- **学习曲线陡**：State / Reducer / Checkpointer / Task / Thread 概念量大
- **杀鸡用牛刀**：简单场景用 [[LangChain]] `create_agent` 更合适
- **调试心智负担**：图执行模型非直觉，需理解 super-step、消息传递、重放
- **生态惯性**：最佳体验绑定 [[LangChain]] + [[LangSmith]]
- **TS 滞后**：LangGraph.js 功能落后 Python 版
- **Pydantic 开销**：State 用 Pydantic 时额外校验成本

## 相关概念

> 以下关系图定义了 LangGraph 所处生态的知识拓扑

| 概念 | 关系 | 方向 |
|------|------|------|
| [[LangChain]] | 用 LangGraph 作为 Agent 运行时 | LangChain → LangGraph |
| [[Deep Agents]] | 在 LangGraph 之上封装高层能力 | Deep Agents → LangGraph |
| [[LangSmith]] | 观测和部署 LangGraph Agent | LangSmith → LangGraph |
| [[Pregel]] | LangGraph 图执行模型的原型 | LangGraph ← Pregel |
| [[Apache Beam]] | API 设计灵感来源 | LangGraph ← Beam |
| [[CrewAI]] | 竞品，偏角色扮演式多 Agent | 平行竞争 |
| [[AutoGen]] | 竞品，偏对话式多 Agent | 平行竞争 |

## 我的理解

把 LangGraph 想象成一个 **智能体工厂的流水线调度系统**：

| 类比 | 对应概念 | 现实含义 |
|------|----------|----------|
| 🏭 产品 | State | 流水线上流转的数据 |
| 👷 工位 | Nodes | 每个工序（调LLM/搜资料/写文件） |
| 🏗️ 传送带 | Edges | 决定产品下一站去哪 |
| 📸 监控摄像头 | Checkpointer | 每步拍照，出问题从照片恢复 |
| 🏷️ 防重标签 | Task | 标记外部操作，恢复时跳过 |
| ⏸️ 暂停按钮 | [[Human-in-the-Loop]] | 关键决策让人拍板 |

**什么时候用哪个？**
- 简单 Agent → [[LangChain]] `create_agent`
- 复杂多步 / 需恢复 / 多Agent / 审批 / 长时 → LangGraph

## 待研究问题

1. Super-Step 并行机制：底层并发模型是 asyncio 还是线程池？
2. Graph API vs Functional API 性能差异？
3. Checkpointer 后端对比：MemorySaver vs PostgresSaver vs SqliteSaver？
4. Streaming 模式：token-level / node-level / custom 的实现细节？
5. 多 Agent 通信：subgraph vs 直接消息传递的适用场景？
6. LangGraph.js 与 Python 版的功能差距？
7. [[Deep Agents]] 到底在 LangGraph 之上封装了什么？迁移场景是？

---

*关联笔记：[[LangChain]] · [[LangSmith]] · [[Deep Agents]] · [[Pregel]] · [[Apache Beam]] · [[CrewAI]] · [[AutoGen]] · [[Durable Execution]] · [[Human-in-the-Loop]]*

*知识结构：[[LangGraph.knowledge.json]]*
