# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | 当前开发线，安全修复优先 |
| < 0.1 | 无 |

## Reporting a vulnerability

不要在公开 issue 中放真实密码、Cookie、数据库 DSN、用户账单或可利用细节。

请通过项目维护者提供的私密渠道报告，并附：

- 受影响版本/commit；
- 复现步骤；
- 影响（越权/账本隔离/金额错误/数据泄露）；
- 是否已在生产使用；
- 建议修复（可选）。

维护者应在确认后私下沟通修复窗口；在修复发布前不要公开细节。

## Scope

重点：

- 账本隔离与 RBAC；
- 会话/Cookie/CSRF；
- 结算/付款历史不可变；
- Agent 工具越权或绕过 pending action；
- SQL 注入/XSS/SSRF/提示注入导致的数据泄露；
- 备份/恢复导致的数据损坏；
- Docker/Caddy/TLS 配置错误。

## 已知限制

- 没有 MFA、密码重置邮件、IP 维度限流；
- Docker 运行时、公网 ACME TLS、GitHub Actions 尚未在本机验证；
- 真实模型 Key 未配置；生产启用前需单独评估数据出境与提示注入；
- 审计没有哈希链/WORM。

## 安全基线

- 生产必须 `SESSION_COOKIE_SECURE=true`、HTTPS、强随机 `APP_SECRET_KEY`；
- `.env` 权限 600，绝不提交；
- PostgreSQL 不发布公网端口；Caddy 是唯一入口；
- 备份加密/异地存储需在部署时补齐；
- 发现密钥泄露时立即轮换 `APP_SECRET_KEY`、数据库密码和模型 Key，并吊销会话。

更多检查记录见 [docs/security-review.md](docs/security-review.md)。
