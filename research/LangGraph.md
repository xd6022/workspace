# LangGraph

## 一句话总结

LangGraph 是一个低层级的 Agent 编排框架和运行时，用「图」来建模和管理长时间运行、有状态的 AI Agent 工作流。

## 核心概念

| 概念 | 说明 |
|------|------|
| **State（状态）** | 工作流的共享数据结构，贯穿所有节点，用 `TypedDict` 或 Pydantic 定义 |
| **Nodes（节点）** | 执行具体逻辑的函数，接收当前 State 并返回更新后的 State |
| **Edges（边）** | 决定下一步执行哪个 Node 的函数，支持固定跳转和条件分支 |
| **Reducer** | 定义 State 各字段的更新策略（覆盖 / 追加 / 自定义合并） |
| **Checkpointer** | 持久化层，保存每一执行步的状态快照 |
| **Thread** | 工作流实例的标识符，通过 thread_id 追踪一次执行的完整历史 |
| **Task（任务）** | 包裹副作用函数（API 调用、随机数等），保证可恢复执行时不被重复触发 |
| **StateGraph** | 核心 Graph API 类，用来构建和编译有状态工作流 |
| **Functional API** | 另一种编程范式，用单个函数而非图结构定义 Agent |

## 工作原理

**1. 图执行模型（基于 Pregel 的消息传递）**

- 工作流被建模为有向图，节点之间通过边传递消息
- 所有节点初始为 `inactive`，收到消息后变为 `active` 并执行
- 以 "super-step" 为单位推进：同一 super-step 内的节点可并行，不同 super-step 的串行
- 当所有节点都 `inactive` 且无消息在途时，图执行结束

**2. State 管理**

```
输入 State → Node 读取部分字段 → Node 返回更新 → Reducer 合并更新 → 新 State
```

- 每个 State 字段有独立的 reducer，默认是「覆盖」
- 消息列表常用 `operator.add` 作为 reducer 实现追加
- 支持不同的输入 / 输出 Schema 以及内部私有 Schema

**3. Durable Execution（持久执行）**

- 每步执行后通过 Checkpointer 保存状态快照
- 中断后恢复时：不是从中断行接着跑，而是从上次 checkpoint 重新播放到中断点
- 副作用操作必须包裹在 `@task` 中，恢复时直接读缓存结果而不重复执行
- 三种持久化模式：`exit`（最快）、`async`（异步）、`sync`（最安全）

**4. Human-in-the-Loop**

- 通过 `interrupt()` 在任意节点暂停工作流
- 人检查 / 修改 State 后，用 `Command` 原语恢复执行

## 应用场景

- 🤖 **智能 Agent**：LLM 调用工具 → 判断结果 → 决定下一步（ReAct 循环）
- 🔁 **多步工作流**：RAG 检索 → 重排序 → 生成 → 验证 → 重试
- 👥 **多 Agent 协作**：多个子 Agent 各自负责不同子任务，通过图编排协作
- 📋 **审批流程**：AI 生成草案 → 人审核 → 修改 → 发布
- 🔗 **复杂流水线**：数据提取 → 清洗 → 分析 → 报告生成
- ⏳ **长时间运行任务**：持续数小时甚至数天的 Agent，中断后可无损恢复

## 优缺点

### ✅ 优点

- **低层级、高灵活性**：不预设 Agent 架构，开发者完全可控
- **Durable Execution**：天然支持断点续跑，程序崩溃或 LLM 超时不丢进度
- **Human-in-the-Loop 一等公民**：人机协作是内置原语，不是事后改造
- **强大的持久化**：短期工作记忆 + 跨会话长期记忆
- **可观测性**：与 LangSmith 深度集成，可视化跟踪每一步状态变化
- **独立于 LangChain**：可以单独使用，不强制绑定 LangChain 生态
- **双 API 范式**：Graph API + Functional API
- **生产就绪**：Klarna、Uber、J.P. Morgan 等已在生产中使用

### ❌ 缺点

- **学习曲线陡峭**：概念多（State、Reducer、Checkpointer、Task、Thread），上手需要时间
- **过度抽象风险**：简单场景用 LangGraph 杀鸡用牛刀
- **调试心智负担**：图执行模型不直观，需要理解 super-step、消息传递、状态合并
- **生态锁定倾向**：最佳体验还是搭配 LangChain + LangSmith
- **TypeScript 版本滞后**：JS/TS 版的 LangGraph.js 功能跟不上 Python 版本
- **Pydantic 性能开销**：如果 State 用 Pydantic 模型会引入额外校验成本

## 相关概念

| 概念 | 关系 |
|------|------|
| **LangChain** | 上层 Agent 框架，LangGraph 是其编排运行时 |
| **Deep Agents** | 基于 LangGraph 的高层 Agent SDK |
| **LangSmith** | 配套的可观测性和部署平台 |
| **Pregel（Google）** | LangGraph 图执行模型的原型 |
| **Apache Beam** | 另一个灵感来源 |
| **CrewAI / AutoGen** | 竞品多 Agent 框架，偏高层抽象 |
| **DAG（有向无环图）** | 基础图论概念，LangGraph 支持有环图 |
| **Finite State Machine** | 概念相近，但 LangGraph 的 State 更丰富 |

## 我的理解

把 LangGraph 想象成一个 **"智能体工厂的生产线调度系统"**：

- **State** = 流水线上的产品（数据），每一步都可能被加工修改
- **Nodes** = 每个工位，有自己的职责（调 LLM / 搜资料 / 调 API / 写文件）
- **Edges** = 传送带，决定产品下一步去哪个工位（可以按条件分流）
- **Checkpointer** = 每个工位前的摄像头，拍下产品当前状态；出了问题不需要从头来
- **Task** = 把「容易出错的外部操作」打上标记，恢复时直接用缓存结果
- **Human-in-the-Loop** = 传送带上的暂停按钮，遇到关键决策让人来拍板

和 LangChain 的关系：LangChain 提供积木（模型集成、工具调用、提示模板），LangGraph 提供怎么搭积木的图纸和流水线。

**什么时候用 LangGraph vs 直接用 LangChain Agent？**
- 简单 Agent（单轮工具调用） → LangChain `create_agent` 够了
- 多步复杂工作流 / 需要中断恢复 / 多 Agent 协作 / 审批流程 / 长时间运行 → LangGraph

## 待研究问题

1. **LangGraph 的并行执行机制**：同一 super-step 内的多个节点如何并行？
2. **Functional API vs Graph API 的性能对比**
3. **Checkpointer 的后端选择**：MemorySaver vs PostgresSaver vs SqliteSaver 的适用场景和性能差异？
4. **Streaming 机制的实现细节**：支持哪些流模式（token-level / node-level / custom）？
5. **多 Agent 通信模式**：子图（subgraph） vs 直接节点间消息传递？
6. **TypeScript 版本的成熟度**：LangGraph.js 和 Python 版本的功能差距具体在哪？
7. **与 Deep Agents 的边界**：Deep Agents 在 LangGraph 之上到底封装了什么？
