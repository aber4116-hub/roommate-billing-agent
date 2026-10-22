# Changelog

## 0.1.0-rc.1 — 2026-10-23

首个可运行的 release candidate。**不是生产就绪版本**。

### Added

- PostgreSQL 16 + SQLAlchemy 2.0 + Alembic，20 张表；
- 整数分守恒分摊；入住天数、规则版本、账单、付款、结算修订；
- 追加式付款/结算行/审计触发器；
- Argon2id、服务端会话、HttpOnly Cookie、CSRF、邀请、RBAC、审计查询；
- Agent Provider/Fake/Disabled、白名单工具、pending action、确认幂等；
- 原生 ES modules 前端、旧版 `data-testid` 契约、严格 CSP；
- Dockerfile、Compose（生产/开发）、Caddyfile、CI、Dependabot；
- `pg_dump`/`pg_restore` 备份恢复脚本与演练；
- README、架构/数据库/API/Agent/安全/部署/测试文档；
- MIT License。

### Verified

- 160 Python tests passed；coverage 88%；
- 5 个 Node 前端纯函数测试；
- Chrome E2E：登录、旧 DOM、规则 v2、账单、实收、锁定、结算、CSV、审计、Agent 降级；
- 本地 Caddy internal CA TLS/反代 200；
- 备份恢复：20 张表一致、恢复库 `/health/ready` 200；
- hadolint/Caddy validate/Compose config 通过；
- pip-audit 无已知第三方依赖漏洞。

### Known limitations

- Docker build/up 未执行（本机无 Docker daemon）；
- 公网 ACME TLS、GitHub Actions 未执行；
- 无 MFA、密码重置邮件、IP 限流；
- 真实模型 Key 未配置；
- 邀请接受/密码修改暂无 UI；
- 新账本初始化仍是手动流程；
- 无镜像漏洞扫描/DAST/对象存储备份。

### Security

- 生产必须 HTTPS、`SESSION_COOKIE_SECURE=true`、强随机密钥；
- `.env` 不入库；Caddy 是唯一公网入口；
- 详见 [SECURITY.md](SECURITY.md) 与 [安全扫描记录](docs/security-review.md)。
