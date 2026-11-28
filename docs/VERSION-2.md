# LumenPilot v2.0.0：从 Agent 可用到可审计的安全边界

## V1 基础版

V1 完成了运营分析 Agent 的主要闭环：

- 查询 LumaFeed 指标和商户口碑风险。
- pgvector 检索运营手册并生成带来源回答。
- LangGraph 工具调用、人工确认和任务创建。
- PostgreSQL checkpoint 持久化多轮会话与中断状态。

这个阶段解决了“Agent 能否完成业务任务”，但还不能清楚回答两个问题：

1. 模型被恶意指令诱导时会不会越权？
2. 模型回答已经允许执行，但质量不合格时如何处理？

## V2 发现的问题

- 只依赖 System Prompt 不能保证工具参数、用户身份和 RAG 文档安全。
- 用户明确说“不要创建任务”时，仍可能由模型误选写工具。
- 流式输出逐 token 下发，手机号或 API Key 可能跨 token 泄露。
- 回答缺少工具数据或来源引用时，系统没有可解释的质量门。
- 质量检查如果只写日志，面试演示和日常排查都不直观。

## V2 设计与实现

### 双层 Agent 边界

```text
用户输入
→ input_guard
→ chat
→ tool_guard
→ tools
→ chat
→ reflection
→ 通过 / 最多修正一次 / 未通过
```

### 安全管控

- 识别中英文 Prompt Injection、系统提示词窃取和越权工具指令。
- 工具白名单限制可执行能力。
- `create_ops_task_draft` 必须具备用户明确的创建意图。
- RAG 结果和模型输出均按不可信内容处理并脱敏。
- 审计只记录输入哈希、分类和会话信息。

### Reflexion 风格质量门

- 检查回答长度、数据工具调用、知识库来源引用和写操作语义。
- 首次不合格时生成确定性反馈，最多重试一次。
- 结果区分 `passed`、`corrected`、`unresolved` 和 `not_run`。
- 通过 Prometheus 指标记录 outcome。
- 前端在回答下方展示质量状态和原因。

这是确定性 Guardrail + 一次 Reflection 重试，不是模型微调，也不是无限自我反思。

## 验证结果

- Ruff：全部通过。
- Pytest：11 项通过。
- Prompt Injection：模型调用前拦截，状态为 `not_run`。
- 正常查询：成功调用指标工具，状态为 `passed`。
- 无来源引用的回答：单元测试确认会触发重试。
- 带 `[operations-playbook#2]` 来源的回答：单元测试确认通过。

## 复盘

V2 的核心收获是区分两种质量问题：

- 安全问题是“这件事不允许做”，必须由代码硬性拦截。
- 质量问题是“允许做但答案不够好”，可以检查、反馈并有限重试。

面试表达时应准确写“Reflexion 风格质量门”，而不是声称训练了 Reflexion 模型。
