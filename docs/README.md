# Knoword 文档索引

> 本目录是 Knoword 项目的**详细技术文档**。[项目入口](../README.md) 在仓库根目录。

## 📚 文档列表

| 文档 | 适合谁 | 何时读 |
|------|--------|--------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 二次开发者、架构师 | 接到这个项目，想搞清楚 5 大 Factory、关键数据流、ADR |
| [API.md](./API.md) | 前端开发者、API 集成方 | 要调某个 REST 端点，看请求/响应/错误码 |
| [OPERATIONS.md](./OPERATIONS.md) | 运维、DBA、部署者 | 部署到生产 / 备份恢复 / 排查错误 |
| [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) | 项目维护者 | 了解文档体系重构的来龙去脉（ADR）|

## 🗺️ 按任务找文档

| 任务 | 看哪里 |
|------|--------|
| 我是新开发者，第一天上手 | [README.md](../README.md) → [ARCHITECTURE.md](./ARCHITECTURE.md) |
| 我要改 / 加一个 LLM Provider | [ARCHITECTURE.md#扩展点](./ARCHITECTURE.md#可扩展点) |
| 我要调某个 API 端点 | [API.md](./API.md) |
| 我要部署到生产 | [OPERATIONS.md#生产部署](./OPERATIONS.md#生产部署) |
| 评估跑失败了 | [OPERATIONS.md#常见错误](./OPERATIONS.md#常见错误) |
| 我要备份数据 | [OPERATIONS.md#备份与恢复](./OPERATIONS.md#备份与恢复) |
| 我想加一个新的评估指标 | [ARCHITECTURE.md#评估系统](./ARCHITECTURE.md#评估系统) |
| 怎么改 chunking 策略 | [ARCHITECTURE.md#chunking](./ARCHITECTURE.md#chunking) |
| 怎么换 embedding 模型 | [OPERATIONS.md#切换-embedding-模型](./OPERATIONS.md#切换-embedding-模型) |

## 🔄 文档维护规则

- **README.md**（根）：项目主入口，每次发版前 review 一次
- **ARCHITECTURE.md**：每次加新模块 / 改数据流必须更新对应章节
- **API.md**：每次改 endpoint 必须同步（建议从代码注释自动生成）
- **OPERATIONS.md**：每次发现新 SOP / 新踩坑必加
- **REFACTOR_PLAN.md**：ADR 类，每次重大决策留档

## 🏷️ 文档版本

| 文档 | 最后更新 | 状态 |
|------|---------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 2026-07 | ✅ 当前版本 |
| [API.md](./API.md) | 2026-07 | ✅ 当前版本 |
| [OPERATIONS.md](./OPERATIONS.md) | 2026-07 | ✅ 当前版本 |
| [REFACTOR_PLAN.md](./REFACTOR_PLAN.md) | 2026-07 | ✅ 当前版本 |

---

**回到**：[项目根目录](../README.md) | [所有文档](./)
