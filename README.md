# LumenPilot

[![Version](https://img.shields.io/badge/version-2.0.0-146b52)](docs/VERSION-2.md)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.121-009688)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0-1c3c3c)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169e1)](https://github.com/pgvector/pgvector)

LumenPilot 是面向 LumaFeed 本地生活内容平台的运营分析 Agent。它通过
只读接口获取内容互动、热门笔记和商户口碑指标，结合 Embedding + pgvector
运营知识检索生成带来源的分析，并在人工确认后创建运营任务。

当前公开版本为 **v2.0.0**。第二版重点补上 Reflexion 风格质量门、Prompt
Injection 防护、工具权限和可视化质量结果，完整演进记录见
[docs/VERSION-2.md](docs/VERSION-2.md)。

## 项目矩阵

- [LumaFeed](https://github.com/LongQz/LumaFeed)：本地生活内容社区
- LumenPilot：LangGraph 运营分析 Agent
- [NovaCart](https://github.com/LongQz/NovaCart)：商城、闪购与 Spring AI 全栈项目

## 核心流程

自动生成的 Mermaid 与 ASCII 流程图：
[docs/generated/langgraph-agent.md](docs/generated/langgraph-agent.md)

```text
运营人员提问
→ 输入安全门
→ LumaFeed 聚合指标工具
→ 工具权限门
→ 运营知识检索工具
→ 带来源的分析报告
→ Reflection 质量检查
→ 人工确认
→ 创建 LumaFeed 运营任务
```

## Reflection 与 AI 安全

Agent 在模型调用前后增加确定性安全与质量边界：

- 输入侧拦截 Prompt Injection、越权指令、超长输入，并对手机号、邮箱和 Token 脱敏。
- 工具侧使用白名单校验，创建任务的写工具必须具备用户明确意图，禁止误触发。
- RAG 文档和模型输出执行不可信内容过滤，检索内容不会被当作系统指令执行。
- Reflection 使用确定性质量规则检查事实引用、工具调用和回答完整性；首次未通过时最多带反馈重试一次。
- 控制台会在每条助手回答下显示“质量检查通过 / 已自动修正 / 质量检查未通过”，便于直接观察 Reflection 结果。
- 安全审计只记录输入哈希与拦截类别，不把原始敏感文本写入日志。

这是生产环境常见的“确定性 Guardrail + 一次 Reflection 重试”，不是重新训练模型，
也不会让模型无限自我反思。实现边界与测试结果见
[docs/ai-safety-and-reflection.md](docs/ai-safety-and-reflection.md)。

## 已实现工具

- `query_platform_metrics`：查询时间段内的用户、笔记、互动趋势与热门内容
- `query_merchant_risk`：查询评分较低、评论量较高的商户
- `search_ops_knowledge`：通过 pgvector 检索社区规范、运营手册和复盘模板
- `create_ops_task_draft`：使用 LangGraph interrupt 等待人工确认后创建任务
- `ask_human`：通用的人工澄清和确认能力

## 先启动 LumaFeed

```powershell
cd ..\LumaFeed\backend
mvn spring-boot:run
```

本地开发默认服务令牌是 `luma-demo-token`。部署前必须同时更换 Java 和 Python
两端的 `LUMAFEED_AGENT_TOKEN`。

## 启动 LumenPilot

```powershell
cd LumenPilot
uv sync
Copy-Item .env.example .env.development
uv run python scripts/run_dev.py
```

在 `.env.development` 中填写模型 API Key、模型名称、PostgreSQL 连接信息和
`LUMAFEED_AGENT_TOKEN`。不要提交该文件。

默认示例使用阿里云百炼的 OpenAI 兼容模式：

```dotenv
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DEFAULT_LLM_MODEL=qwen4-max
LLM_MODELS=qwen4-max,qwen3.7-plus
LONG_TERM_MEMORY_EMBEDDER_MODEL=text-embedding-v3
LONG_TERM_MEMORY_EMBEDDING_DIMS=1024
```

打开：

```text
http://127.0.0.1:8000/docs
```

浏览器测试控制台：

```text
http://127.0.0.1:8000/console/
```

控制台包含普通用户注册/登录、独立会话、Agent 对话、人工确认、管理端账号列表、
运营任务和 LumaFeed 指标快照。开发环境会初始化以下管理员账号：

```text
admin.qzh@lumafeed.local   / qzh
admin.ops@lumafeed.local   / qzh
admin.audit@lumafeed.local / qzh
```

账号数据保存在 LumaFeed 的 `lumafeed` MySQL 数据库，新建独立表
`tb_lumenpilot_account`。PostgreSQL 继续负责会话、LangGraph checkpoint、
长期记忆和 pgvector 检索。

每次创建 LangGraph Agent 时会自动导出：

```text
docs/generated/langgraph-agent.mmd
docs/generated/langgraph-agent.md
docs/generated/langgraph-agent.png
```

Markdown 版本可以直接在 GitHub 中渲染；PNG 渲染依赖 Mermaid 服务，失败时
Mermaid 和 ASCII 图仍会保留，不会影响 Agent 启动。

## API 安全边界

- LumaFeed 不向模型暴露数据库凭据。
- LumenPilot 使用服务端令牌调用固定分析接口，模型看不到服务令牌。
- 所有写操作必须经过明确的人工确认。
- 检索到的运营文档只作为业务资料，不作为系统指令执行。
- 被输入安全门拦截的请求不会继续调用 LLM 或工具。
- 工具调用、Reflection 结果和安全拦截均写入结构化审计日志与 Prometheus 指标。

## 项目结构

```text
app/core/langgraph/tools/   LumaFeed 运营工具
app/services/lumafeed.py    Java 运营接口客户端
app/services/knowledge.py   运营知识向量索引、检索与词法降级
knowledge/                  Markdown 运营手册
evals/                      Agent 质量评估
```

## 来源与许可证

This project is derived from
[wassim249/fastapi-langgraph-agent-production-ready-template](https://github.com/wassim249/fastapi-langgraph-agent-production-ready-template),
Copyright (c) 2025 Wassim EL BAKKOURI, licensed under the MIT License.

The original license is retained in [LICENSE](LICENSE). See
[NOTICE.md](NOTICE.md) and [AUTHORS.md](AUTHORS.md).

## Author

LongQz
