# Docker 运行时验证（QEMU TCG）

- 状态：**Docker build + run + 健康检查 + UI 登录已实际通过**。
- 环境：Windows 主机无 Docker daemon、Hyper-V/Containers/VirtualMachinePlatform 均 Disabled；使用 **QEMU 11.1.0 TCG + boot2docker 19.03.12** 做验证。
- 这不是生产宿主：QEMU 无 KVM，性能低；boot2docker 的 Docker 19 较旧。

---

## 1. 结果

```text
Docker Engine 19.03.12 / API 1.40
QEMU 11.1.0 TCG，4 vCPU / 4 GiB
镜像：roommate-billing-agent:qemu
镜像 ID：ce80e9322d42
大小：215MB
容器：rba-db (postgres:16-alpine) + rba-api (healthy)
```

宿主机经 SSH 隧道访问 `http://127.0.0.1:18080/`：

```text
GET /health/ready -> 200 {"status":"ok"}
页面登录 -> 演示合租账本 · owner
12 cells / 4 bill totals / 3 person totals / ¥493.05
浏览器 exceptions: []
```

截图：`_runtime/docker-dashboard.png`。

---

## 2. 实际命令

```bash
docker build -t roommate-billing-agent:qemu .
docker network create rba-net

docker run -d --name rba-db --network rba-net \
  -e POSTGRES_USER=roommate \
  -e POSTGRES_PASSWORD=<demo-password> \
  -e POSTGRES_DB=roommate \
  -v rba-db:/var/lib/postgresql/data \
  postgres:16-alpine

docker run -d --name rba-api --network rba-net -p 8000:8000 \
  --security-opt seccomp=unconfined \
  -e DATABASE_URL=postgresql+psycopg://roommate:<demo-password>@rba-db:5432/roommate \
  -e APP_SECRET_KEY=<64-hex> \
  -e APP_BASE_URL=http://127.0.0.1:18080 \
  -e SESSION_COOKIE_SECURE=false \
  -e LLM_ENABLED=false \
  -e WEB_DIR=/app/web \
  roommate-billing-agent:qemu
```

> `--security-opt seccomp=unconfined` 只用于旧 Docker 19 + Python 3.12 的 `clone3` 兼容问题；生产现代 Docker 不应默认使用，必须重新验证 seccomp 下的 Argon2 启动。

---

## 3. 发现并修复的问题

### 3.1 缺少 httpx

首次启动：

```text
ModuleNotFoundError: No module named 'httpx'
```

`agent/providers.py` 导入 httpx，但 `httpx` 只在 dev extra。已移到运行时依赖，并重新构建。

### 3.2 旧 Docker seccomp 阻止 Python 线程

```text
argon2.exceptions.HashingError: Threading failure
```

Docker 19 默认 seccomp 与 Python 3.12/glibc 的 `clone3` 不兼容；QEMU 验证用 `seccomp=unconfined` 绕过。现代 Docker/containerd 需要重新验证默认 seccomp。

### 3.3 pip 进度条线程

旧 seccomp 下：

```text
RuntimeError: can't start new thread
```

设置 `PIP_PROGRESS_BAR=off` 后构建通过。

### 3.4 健康检查超时

QEMU TCG 下 5s timeout 不足：

```text
Health check exceeded timeout (5s)
```

已改为 `timeout=15s`、`start-period=60s`、请求 timeout 10s；容器转为 healthy。

---

## 4. 未验证

- `docker compose up`（只做了 `compose config`）；
- Docker 内 Caddy / 公网 ACME；
- 镜像漏洞扫描（Trivy/Grype）、DAST；
- 现代 Docker Engine 的默认 seccomp 复测；
- 生产资源/并发/长期运行。

因此该证据只证明 **镜像能构建并在一个 Linux Docker 里启动**，不证明生产部署完成。
