# AI 安全与 Reflection 质量门

## 目标

LumenPilot 可以在没有人工盯守的情况下查询运营数据并起草任务，因此需要同时控制
输入、工具执行、知识库内容和最终回答。当前实现采用确定性规则，模型不负责自行
判断是否越过安全边界。

## 执行链路

```text
用户输入
→ input_guard：Prompt Injection、长度、敏感信息
→ chat：模型推理与工具选择
→ tool_guard：工具白名单、写操作意图
→ tools：只读接口或人工确认
→ chat：基于工具结果生成回答
→ reflection：事实来源、工具调用、回答完整性
→ 通过或最多重试一次
```

## Reflection 的准确定位

本项目实现的是 **Reflexion 风格的质量门**：

1. 对当前轮回答执行确定性规则检查。
2. 发现缺少工具结果、缺少知识库引用、回答过短或疑似泄露规则时，生成整改反馈。
3. 将反馈追加到系统提示词，最多重新生成一次。
4. 第二次仍未通过时记录 `unresolved`，不会无限循环。

它不是 Reflexion 论文中的完整“长期经验记忆 + 多轮自我反思 + 策略学习”，也没有
训练或微调模型。这个实现更适合业务接口：结果可解释、延迟可控、行为可测试。

聊天接口会返回 `reflection.status`、`reflection.attempts` 和 `reflection.reason`。
控制台会把结果展示为“质量检查通过”“已自动修正”“质量检查未通过”或“未执行”，
因此不需要只依赖后台日志判断是否发生 Reflection。

## 安全控制

### 输入安全

- 拦截典型中英文 Prompt Injection、系统提示词窃取、Shell/SQL 执行和越权表达。
- 单次输入限制为 3000 字符。
- 手机号、邮箱、API Key 和 Bearer Token 在进入模型或写日志前脱敏。

### 工具安全

- 只允许已注册的运营工具执行。
- 单轮工具调用数量有限制。
- `create_ops_task_draft` 必须由用户明确提出创建、发起或安排任务。
- 用户说“不要创建任务”时，即使模型选择了写工具也会被阻止。

### RAG 与输出安全

- 运营知识片段先经过注入检测和脱敏，再作为不可信业务资料返回。
- 模型回答和历史输出再次执行脱敏。
- 回答中出现疑似注入或规则泄露内容时进入 Reflection 重试。

### 审计与指标

- 审计日志只保存脱敏输入的 SHA-256 前缀、会话和拦截类别。
- `ai_safety_blocks_total` 统计输入门与工具门拦截。
- `reflection_outcomes_total` 统计 passed、retry 和 unresolved。

## 测试

```powershell
uv run ruff check .
uv run pytest tests/test_ai_safety.py -q
```

当前验证结果：

- Ruff：通过。
- Pytest：`11 passed`。
- 真实接口：Prompt Injection 在模型调用前被拒绝，回答显示“已阻止本次请求”。
- 真实接口：正常指标查询成功调用 `query_platform_metrics`，未误触发任务创建，
  审计日志记录 `reflection_passed`。

## 已知边界

- 规则拦截适合常见攻击和业务边界，但不能替代模型供应商的上下文安全能力。
- 需要进一步生产化时，可把限流改为 Redis 分布式限流，把审计日志接入 ELK 或
  数据库，并增加恶意样本回归集和延迟监控。
