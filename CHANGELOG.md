# Changelog

## v2.0.0 - 2026-11-28

### Added

- LangGraph `input_guard → chat → tool_guard → tools → reflection` 执行链路。
- Reflexion 风格确定性质量门，首次失败时最多带反馈重试一次。
- Prompt Injection、越权指令、敏感信息脱敏和输入长度限制。
- 工具白名单、写操作明确意图校验和不可信 RAG 内容过滤。
- `ai_safety_blocks_total`、`reflection_outcomes_total` 监控指标。
- 前端展示“质量检查通过 / 已自动修正 / 未通过 / 未执行”及原因。
- 隐私审计日志，只记录脱敏输入哈希。

### Changed

- 流式接口在整张图完成后只输出 Reflection 选中的最终答案，避免重试草稿泄漏。
- 控制台静态资源增加版本号，便于发布后刷新缓存。

## v1.0.0

- 完成运营指标、商户口碑、知识检索和任务创建工具。
- PostgreSQL checkpoint、人工确认、多轮会话和运营分析控制台。
