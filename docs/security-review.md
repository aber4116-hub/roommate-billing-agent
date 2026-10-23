# 阶段 7 安全检查记录

- 日期：2026-10-23
- 范围：Python 依赖、Dockerfile、Compose、Caddyfile、前端 CSP、部署配置
- 原则：**只记录实际执行过的检查**；未执行项明确列为未验证。

---

## 1. 已执行

### 1.1 Python 依赖漏洞扫描

工具：`pip-audit 2.10.1`（uv tool 安装，扫描项目 `.venv`）。

```text
Name                   Skip Reason
roommate-billing-agent Dependency not found on PyPI and could not be audited
No known vulnerabilities found
```

- 本项目自身不在 PyPI，跳过是预期行为；
- 第三方依赖未发现已知漏洞；
- 结果对应 2026-10-23 的漏洞库。

### 1.2 Dockerfile lint

工具：`hadolint 2.15.1`。

```text
exit=0
```

已修复：

- `USER app` → `USER 10001:10001`
- `HEALTHCHECK` 改为 JSON 形式
- 非 root、多阶段构建、固定运行时基础镜像

### 1.3 Compose 配置

工具：Docker Compose CLI `v5.6.1`（无 Docker daemon，仅解析/插值）。

```text
docker compose --env-file .env.example -f docker-compose.yml config --quiet
prod_exit=0

docker compose --env-file .env.example -f docker-compose.dev.yml config --quiet
dev_exit=0
```

验证内容：服务名、依赖、网络、卷、环境变量必填项、`env_file` 可选文件。

### 1.4 Caddyfile

工具：Caddy `v2.11.7`。

```text
caddy validate --config Caddyfile --adapter caddyfile
Valid configuration
exit=0
```

配置包含：

- 自动 HTTPS；
- HSTS（含子域，未 preload）；
- `X-Content-Type-Options`、`X-Frame-Options`、`Referrer-Policy`、`Permissions-Policy`；
- 隐藏 `Server`；
- 1 MB 请求体上限；
- JSON 访问日志到 stdout。

本机内部 CA 实跑（非公网 ACME）：

```text
https://localhost:8443/health/ready -> 200 {"status":"ok"}
https://localhost:8443/             -> 200，CSP 生效
https://localhost:8443/api/v1/meta  -> 200
http://localhost:8080/...           -> 301 到 https://localhost:8443/...
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
```

测试使用 Caddy internal CA，客户端忽略证书校验；生产公网 ACME 仍未验证。

### 1.5 前端 CSP / 安全头

`tests/integration/test_web.py`：

- `/` 返回 200；
- CSP 包含 `default-src 'self'`、`script-src 'self'`、`style-src 'self'`；
- 无 `unsafe-inline`；
- 无内联 `<script>`、`style=""`、`onclick`；
- `X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`；
- `/docs` 不被 CSP 阻断。

结果：3 tests passed。

### 1.6 备份恢复

见 [backup-restore.md](backup-restore.md)。真实执行：

- `pg_dump -Fc` + SHA-256；
- `pg_restore` 到独立库；
- 20 张表行数一致；
- `bill_cents=49305`、`payment_cents=12000`、`audit_logs=9`；
- 恢复库 `/health/ready` 200；
- `alembic_version=f9d42243af3a`。

### 1.7 配置/密钥检查

- `.env` 被 `.gitignore` 与 `.dockerignore` 忽略；
- `.env.example` 只有 `CHANGE_ME` 占位符；
- Compose 不发布 PostgreSQL 端口；
- API 不发布宿主机端口（生产 compose）；
- Caddy 是唯一 80/443 入口；
- 容器 `read_only`、`cap_drop: ALL`、`no-new-privileges`（API/Caddy）；
- 登录 Cookie `Secure` 由生产 `.env` 开启；
- 未在仓库中发现真实密码/API Key。
- 实际扫描 164 个非 `.env`/非运行时文件：数据库密码与 `APP_SECRET_KEY` 命中 **0**。

---

### 1.8 CI workflow lint

- `actionlint 1.7.12`：`.github/workflows/ci.yml` exit 0；
- Workflow 包含 test 与 docker job；
- 仅静态 lint，**未在 GitHub runner 运行**。

---

## 2. 未执行 / 未验证

- **Docker 镜像构建与运行**：本机无 daemon；已用 QEMU TCG + boot2docker 19.03 执行 build/run，镜像 215MB、容器 healthy。旧 Docker 19 的 seccomp 需 `--security-opt seccomp=unconfined` 才能跑 Python 3.12/Argon2；现代 Docker 默认 seccomp 必须重新验证。
- **GitHub Actions 实际运行**：本地没有 GitHub 远程仓库；只编写并静态检查 workflow，未在 GitHub runner 上跑。
- **公网 TLS/ACME**：本地 internal CA 已跑通，但未配置公网域名/DNS，未做 ssllabs；生产证书续期未演练。
- **容器镜像漏洞扫描**：未运行 Trivy/Grype/Scout。
- **DAST/渗透测试**：未执行。
- **速率限制/WAF**：未实现；阶段 4 只有账户锁定。
- **MFA**：未实现。
- **备份异地/对象存储/加密**：未接入。
- **CI 的 Docker job**：workflow 中已定义，但未在 GitHub 上验证。
- **Docker 内 Caddy HTTPS**：已启动 `caddy:2-alpine`，internal CA、HSTS/CSP、HTTPS 登录通过；公网 ACME 未验证。
- **Compose 编排**：Compose v5.6.1 dev up 通过（db/api healthy）；QEMU 旧 Docker 需 seccomp/端口 override。

---

## 3. 结论

- 依赖、Dockerfile 静态规则、Compose 解析、Caddyfile、CSP、备份恢复均已实际检查；
- **不能声称 Docker 部署已完成**，也不能声称 CI 已绿；
- 生产上线前必须补齐：Docker 构建/运行、公网 ACME TLS、CI 首次运行、镜像扫描、限流/WAF 决策。
