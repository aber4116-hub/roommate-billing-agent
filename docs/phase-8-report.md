# 阶段 8 报告：文档、许可证与本地 GitHub 交付

- 状态：**本地 release candidate 已完成；尚未创建 GitHub 远程仓库、未 push**。
- 版本：`v0.1.0-rc.1`。
- 许可证：MIT（`legacy/` 用户提供文件除外，见 `NOTICE`）。
- Docker/CI 运行时仍未验证；本版本不是生产就绪版。

---

## 1. 已完成

### 1.1 文档/社区文件

- `README.md`：功能、文档索引、实测结果、本地运行、Docker 命令、限制、License；
- `CONTRIBUTING.md`：开发/测试/PR/安全规则；
- `SECURITY.md`：私下报告、范围、已知限制、基线；
- `CHANGELOG.md`：`0.1.0-rc.1`；
- `RELEASE_NOTES.md`：release candidate 说明；
- `LICENSE`：MIT；
- `NOTICE`：说明 `legacy/` 不在 MIT 范围；
- `.gitattributes`、`.editorconfig`、`Makefile`；
- GitHub issue/PR 模板、Dependabot、CI workflow。

### 1.2 本地 Git

```text
branch: main
tag:    v0.1.0-rc.1
tracked files: 以 `git ls-files` 为准
```

- `.env`、`.venv`、`_runtime`、`.coverage`、备份、缓存均未入库；
- 从 bundle 克隆验证：tag 正确、`LICENSE`/`web` 存在、无 `.env`；
- 工作区 clean。

### 1.3 交付物

运行时产物（不提交仓库）：

```text
_runtime/roommate-billing-agent-v0.1.0-rc.1.bundle
_runtime/roommate-billing-agent-v0.1.0-rc.1.zip
_runtime/SHA256SUMS
```

具体哈希以 `_runtime/SHA256SUMS` 为准（发布后生成）。

`git bundle` 可完整恢复 main 与 tag；zip 是 `git archive HEAD`。

---

## 2. 验证

- 160 Python tests passed；coverage 88%；
- Node 5 tests passed；
- Chrome E2E passed；
- Caddy 内部 CA TLS/反代 200；
- 备份恢复 20 张表一致、恢复库 `/health/ready` 200；
- hadolint / compose config / Caddy validate 通过；
- pip-audit 无已知第三方依赖漏洞；
- bundle clone 校验通过。

---

## 3. 未完成 / 阻塞

| 项 | 原因 |
|---|---|
| GitHub 远程仓库 | 本机没有 `gh`、`GITHUB_TOKEN`、远程 URL |
| `git push` / PR / Release | 同上 |
| GitHub Actions 首次运行 | 无远程仓库 |
| Docker build/up | 本机无 Docker daemon，Hyper-V/Containers 未启用 |
| 公网 ACME TLS | 无域名/DNS/公网入口 |
| 公开仓库 | 默认 Private；`legacy/` 权利未确认，公开前需移除或取得许可 |

因此：

- 不声称“已发布到 GitHub”；
- 不声称“CI 绿”；
- 不声称“生产就绪”。

---

## 4. 下一步（需要用户/环境）

1. 提供 GitHub 远程 URL 与推送权限（或在本机登录 `gh`）；
2. 决定 Private/Public；
3. 公开前处理 `legacy/合租账单分摊器.html`（MIT 不覆盖）；
4. 在有 Docker 的 Linux 主机执行 build/up、TLS、CI；
5. 通过后打正式 `v0.1.0` / `v1.0.0`。

在此之前，本地 bundle/zip 是可转交的完整源码交付。
