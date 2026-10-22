# Contributing

## 开发环境

- Python 3.12+
- PostgreSQL 16+
- Node.js 24（仅前端纯函数测试）
- 可选：Docker Engine + Compose v2（用于容器验收）

## 初始化

```bash
uv sync --frozen --extra dev
cp .env.example .env
# 本地开发把 DATABASE_URL 改为本地 PostgreSQL，SESSION_COOKIE_SECURE=false
alembic upgrade head
```

## 提交前检查

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run alembic check
node --test web/tests/format.test.mjs
```

涉及部署文件时：

```bash
docker compose --env-file .env.example -f docker-compose.yml config --quiet
docker compose --env-file .env.example -f docker-compose.dev.yml config --quiet
caddy validate --config Caddyfile --adapter caddyfile
hadolint Dockerfile
```

## 代码规则

- 金额只用整数分；禁止浮点参与分摊。
- 所有账单分摊必须逐笔守恒；零头归规则指定人。
- 已确认的付款、结算行、审计只追加，不原地改历史。
- 跨账本访问必须返回 404，不泄露其他账本存在性。
- Agent 写操作只能创建 pending action；确认必须由用户触发。
- 前端不存 API Key；金额显示与输入都经过 `format.js`。
- 新增 API 必须有权限、幂等、错误码和测试。
- 不提交 `.env`、真实密码、生产数据、备份文件。

## PR

- 说明动机、行为变化、测试命令和真实结果。
- 数据库变更必须包含 Alembic 迁移和 up/down/up 验证。
- UI 变更必须说明旧 `data-testid` 是否保留。
- 安全相关变更请先读 [SECURITY.md](SECURITY.md)。

## License

提交即表示同意以 [MIT](LICENSE) 许可贡献。
