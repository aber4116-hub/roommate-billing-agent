## What changed

## Why

## Verification

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pytest -q`
- [ ] `uv run alembic check`
- [ ] `node --test web/tests/format.test.mjs`（前端变更）
- [ ] 旧 `data-testid` 保留/说明（前端变更）
- [ ] 迁移 up/down/up（数据库变更）
- [ ] Docker/Compose/Caddy 静态检查（部署变更）

## Safety

- [ ] 未提交 `.env`、密码、真实账单或备份
- [ ] 财务写操作仍需用户确认
- [ ] 跨账本/权限测试已覆盖
