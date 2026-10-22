# v0.1.0-rc.1

这是 `roommate-billing-agent` 的第一个可运行 release candidate，**不是生产就绪版本**。

## 包含

- 多用户合租账本、账单、入住天数、规则版本、实收、结算修订；
- 整数分守恒分摊；零头归规则指定人员；
- Argon2id 登录、服务端会话、CSRF、邀请、RBAC、审计；
- Agent Provider/工具白名单/pending action/确认幂等；
- 原生 ES modules 前端、旧版 DOM 测试契约、严格 CSP；
- 账户对话框：修改密码、接受邀请；
- Dockerfile、Compose（生产/开发）、Caddyfile、GitHub Actions、Dependabot；
- `pg_dump`/`pg_restore` 备份恢复脚本；
- MIT License（`legacy/` 文件除外，见 NOTICE）。

## 已验证

```text
160 Python tests passed
coverage 88%
5 Node frontend tests passed
Chrome E2E passed
Caddy internal CA TLS/proxy passed
backup/restore: 20 tables identical
recovery /health/ready: 200
hadolint / caddy validate / compose config passed
pip-audit: no known third-party vulnerabilities
```

## 未验证

- Docker build / compose up（本机无 Docker daemon）；
- 公网 ACME TLS；
- GitHub Actions 首次运行（无远程仓库）；
- 镜像漏洞扫描/DAST；
- 真实模型 Key/生产模型调用。

## 安装

见 [README](README.md) 的本地运行与 Docker 章节。

## 升级/回滚

数据库使用 Alembic；升级前先备份：

```bash
PG_DATABASE_URL='postgresql://...' ./scripts/backup_postgres.sh
```

## 安全

- 不要提交 `.env`、真实账单、备份或模型 Key；
- 生产必须 HTTPS + `SESSION_COOKIE_SECURE=true` + 强随机密钥；
- 漏洞报告见 [SECURITY.md](SECURITY.md)。
