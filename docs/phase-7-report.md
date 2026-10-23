# 阶段 7 报告：Docker/CI/备份恢复/安全检查

- 状态：**交付物已完成；Docker build/run 已在 QEMU/boot2docker 实际通过；Compose dev up、Docker 内 Caddy HTTPS 已通过；GitHub Actions 未执行**。
- 当前主机没有 Docker daemon；Hyper-V/Containers 未启用，WSL 无发行版。改用 QEMU TCG + boot2docker 完成 Docker build/run（非生产验证）。
- Caddy 已在本机用内部 CA 完成真实 TLS 握手/反代测试（`https://localhost:8443` → `127.0.0.1:8001`），公网 ACME/域名未验证。
- 因此本阶段**不能**标记为“全新环境部署已通过”。下面区分“已验证”和“未验证”。

---

## 1. 交付物

```text
Dockerfile
.dockerignore
docker-compose.yml
docker-compose.dev.yml
Caddyfile
.env.example
.github/workflows/ci.yml
.github/dependabot.yml
scripts/backup_postgres.sh
scripts/backup_postgres.ps1
scripts/restore_postgres.sh
scripts/restore_postgres.ps1
docs/backup-restore.md
docs/security-review.md
```

---

## 2. 已实际验证

### 2.1 Dockerfile lint

- hadolint `2.15.1`；
- 结果 `exit=0`；
- 已修复 `USER app` → `USER 10001:10001`、HEALTHCHECK JSON 形式；
- 多阶段、非 root、`.dockerignore` 排除 `.env`。

### 2.2 Compose 解析

- Docker Compose CLI `v5.6.1`（无 daemon，仅 `config --quiet`）：

```text
prod_exit=0
dev_exit=0
```

- 验证了 `db/api/caddy` 与 `db/api` 两种拓扑；
- `.env` 的 `env_file` 为可选，CI/无 `.env` 时仍能解析；
- 数据库不发布宿主机端口；生产只发布 Caddy 80/443。

### 2.3 Caddyfile

- Caddy `2.11.7`：

```text
Valid configuration
exit=0
```

- 自动 HTTPS、HSTS、X-Frame-Options、Referrer-Policy、Permissions-Policy、请求体 1MB、隐藏 Server；
- 本机内部 CA 实跑：`/health/ready` 200、`/` 200、`/api/v1/meta` 200、HTTP 8080 → HTTPS 8443 301；
- 公网域名/ACME 证书未验证。

### 2.4 备份恢复（真实执行）

见 [backup-restore.md](backup-restore.md)。

- `pg_dump -Fc` + SHA-256；
- `pg_restore` 到独立库；
- 20 张表逐表行数一致；
- `bill_cents=49305`、`payment_cents=12000`、`audit_logs=9`；
- `alembic_version=f9d42243af3a`；
- 恢复库应用 `/health/ready` 200、`/` 200、`/api/v1/meta` 200。

备份 SHA-256：

```text
0c747bf22c5603621ac4ce112f9a5014bbce62728d06b00a377309857c1b7825
```

### 2.5 安全

见 [security-review.md](security-review.md)。

- `pip-audit 2.10.1`：第三方依赖无已知漏洞；本地项目因不在 PyPI 被跳过；
- hadolint 通过；
- Compose/Caddy 静态验证通过；
- CSP/安全头测试通过；
- 未发现真实密码/API Key 进入版本库。

### 2.6 CI 静态检查

- `actionlint 1.7.12`：`.github/workflows/ci.yml` 通过（exit 0）；
- workflow YAML 可解析（PyYAML），包含 test/docker 两个 job；
- **未在 GitHub runner 实际运行**。

### 2.7 CI 本地等价检查

- `ruff check` / `ruff format --check`；
- `pytest`（160 passed，88%）；
- `alembic check`（无漂移）；
- `compileall`；
- Node 纯函数测试（5 passed）；
- JavaScript syntax；
- Compose config、Caddy validate、hadolint。

### 2.8 Docker build/run（QEMU）

由于本机不能启用 Hyper-V/WSL，使用 QEMU 11.1.0 TCG + boot2docker 19.03.12 做实际验证：

```text
Docker 19.03.12 / API 1.40
镜像：roommate-billing-agent:qemu  ce80e9322d42  215MB
容器：rba-db (postgres:16-alpine) + rba-api (healthy)
/health/ready -> 200 {"status":"ok"}
登录后：12 cells / ¥493.05 / 无 JS 异常
```

发现并修复：

- 运行时缺少 `httpx`（Agent provider 导入失败）→ 加入 `pyproject` 运行时依赖；
- 旧 Docker 19 的 seccomp 阻止 Python 3.12 `clone3`，导致 Argon2 `Threading failure`；QEMU 验证使用 `--security-opt seccomp=unconfined`，现代 Docker 仍需复测；
- pip 在旧环境起线程失败 → `PIP_PROGRESS_BAR=off`；
- 健康检查 5s 在 TCG 下超时 → 调整为 15s/timeout、60s start-period，容器转 healthy。

Docker 内 Caddy HTTPS、Compose dev up 已通过。限制：Compose 用了 QEMU seccomp/端口 override；镜像扫描/DAST 未做；QEMU 仅作验证，不是生产宿主。详见 [Docker 运行时验证](docker-runtime.md)。

---

## 3. 未验证 / 阻塞项

| 项 | 原因 | 状态 |
|---|---|---|
| `docker build` | 主机无 daemon，改用 QEMU TCG | **已执行**（镜像 215MB） |
| `docker compose up` | Compose v5.6.1 dev + QEMU override | **已执行**（db/api healthy） |
| Caddy 容器 HTTPS | 已用 caddy:2-alpine + internal CA | **已执行** |
| Caddy 公网 ACME TLS | 无公网域名/DNS | **未执行** |
| GitHub Actions 运行 | 无远程仓库/未 push | **未执行** |
| 镜像漏洞扫描（Trivy/Grype） | 镜像已构建，未安装扫描器 | **未执行** |
| DAST/渗透 | 未安排 | **未执行** |
| 对象存储/异地备份 | 未接入 | **未执行** |
| 备份加密 | 未实现 | **未执行** |

因此：

- 不声称“全新环境部署通过”；
- 不声称“CI 绿”；
- 不声称“HTTPS 已上线”。

---

## 4. 环境事实

```text
docker --version        -> 无输出/命令不存在
podman --version        -> 无
wsl --status            -> 无已安装发行版
Microsoft-Hyper-V-All   -> Disabled
Containers              -> Disabled
```

启用 Hyper-V/Containers 需要重启系统；不在本会话中擅自重启宿主。需要以下任一条件才能完成运行时验收：

1. 一台有 Docker Engine + Compose v2 的 Linux 主机；或
2. 允许启用 WSL2/Hyper-V 并重启的 Windows 主机；或
3. 可用的远程 Docker 上下文。

---

## 5. 结论

阶段 7 的**配置、脚本、静态验证、备份恢复、安全扫描**已完成；**运行时部署和 CI 执行**仍缺环境。

下一步二选一：

- 在具备 Docker 的环境执行 `docker compose up -d --build`、TLS/健康检查、首次 CI，再关闭阶段 7；
- 或用户明确接受“Docker 仅交付未运行”，继续阶段 8（README/LICENSE/GitHub），但发布说明必须保留该限制。
