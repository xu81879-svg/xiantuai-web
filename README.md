# 鲜图 AI MVP

当前仓库已升级为可部署的 MVP：Vue 3 工作台由 FastAPI 单服务托管，具备中文登录/注册、JWT 鉴权、商品与生成记录持久化、Alembic 数据库迁移、图片上传入口和 Railway 部署配置。亚洲客户默认使用 `zh-CN` 与 `Asia/Shanghai`，后续可扩展日本、韩国和东南亚地区的 locale、timezone、支付和对象存储策略。

Railway 部署请阅读 [`RAILWAY.md`](RAILWAY.md)，生产入口为根目录 [`Dockerfile`](Dockerfile) 和 [`railway.toml`](railway.toml)；`docker-compose.yml` 仅用于本地多服务开发，Railway 不直接执行 Compose。

## MVP 当前功能

- 账号注册、登录、JWT 会话和用户隔离。
- 商品新增、列表、图片上传与识别接口。
- 生成任务记录、素材列表和生成历史持久化。
- SQLite 开发环境与 Railway PostgreSQL 兼容。
- Alembic 初始迁移，生产启动时自动执行 `alembic upgrade head`。
- Vue 工作台、响应式移动端适配、单服务静态托管。

---

以下为基础模板与本地开发说明。

Vue 3 + FastAPI + PostgreSQL + Redis 的安全开发骨架。当前前端提供首页草稿交互，后端提供健康检查和基础配置；AI Pipeline、认证、任务队列和业务数据模型仍需在此基础上实现。

## 目录结构

```text
.
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py       # Pydantic Settings 配置
│   │   └── main.py         # FastAPI 应用
│   ├── .env.example
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/Home.vue
│   │   ├── App.vue
│   │   ├── main.ts
│   │   └── router.ts
│   ├── Dockerfile
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
└── docker-compose.yml
```

## 启动

```bash
cp backend/.env.example backend/.env
# 仅开发环境使用；生产环境请通过密钥管理系统注入变量

docker compose up --build
```

- 前端：http://localhost:5173
- API：http://localhost:8000
- API 文档：http://localhost:8000/docs
- 就绪检查：http://localhost:8000/readyz

`backend/.env` 被 `.gitignore` 忽略，禁止提交真实密钥。生产环境必须替换默认数据库口令，并使用独立的 Secret 管理方案。

## 配置说明

`backend/app/config.py` 使用 Pydantic Settings 读取环境变量。环境变量名不区分大小写；逗号分隔的 `ALLOWED_ORIGINS` 会被解析为 CORS 白名单。生产环境请设置：

```dotenv
ENVIRONMENT=production
DEBUG=false
ALLOWED_ORIGINS=https://your-frontend.example.com
```

不要把 `ALLOWED_ORIGINS` 设置为 `*`，也不要在生产环境启用宽泛的 CORS 或调试模式。

## Compose 安全改动

- PostgreSQL 和 Redis **不再映射宿主机端口**，仅通过 Compose 内部网络访问。
- API 和前端只绑定到 `127.0.0.1`，避免默认暴露到公网；若需要通过反向代理提供服务，应由 Nginx / Caddy 负责 TLS、认证和限流。
- PostgreSQL 和 Redis 增加健康检查；API 等后端服务等待 `service_healthy` 后启动。
- `.env` 采用可选加载，避免首次创建文件前 Compose 直接失败；生产环境不应依赖仓库内的默认值。
- Redis 开启 AOF 持久化，并使用独立命名卷。
- 生产部署仍需：替换数据库口令、限制 Docker socket 权限、配置备份、日志脱敏、网络策略和镜像漏洞扫描。

### 本机调试数据库 / Redis

不要直接把端口永久写回主 Compose。可临时建立未提交的 `docker-compose.override.yml`，并绑定回环地址：

```yaml
services:
  postgres:
    ports: ["127.0.0.1:5432:5432"]
  redis:
    ports: ["127.0.0.1:6379:6379"]
```

## 数据与升级

常规升级：

```bash
docker compose up -d --build
```

**不要把 `docker compose down -v` 作为常规升级命令**；它会删除 `pg`、`redis` 和 `storage` 命名卷，可能导致数据库、缓存和生成文件丢失。只有在明确重置开发数据、且已确认不需要保留数据时才使用该命令。

正式项目应使用 Alembic 等迁移工具管理数据库 schema，部署前执行备份并验证恢复流程。

## 本地检查

```bash
# 后端语法检查（无需数据库）
python -m compileall backend/app

# 前端依赖安装与构建（需要 Node.js）
cd frontend
npm install
npm run build

# Compose 配置检查（需要 Docker Compose）
docker compose config
```

## 当前边界

这是基础模板，不是生产成品。尚未包含用户认证、短信验证码、真实 AI Provider、数据库模型、队列 Worker、文件上传鉴权、额度并发扣减、支付回调验签、内容审核和 Alembic 迁移。接入这些能力前，应增加对应的单元测试、集成测试与安全审查。


## 自动化测试

后端测试：

```bash
cd backend
python -m pytest
```

前端测试与构建：

```bash
cd frontend
npm install
npm test
npm run build
```

测试覆盖当前基础模板的健康检查、Prometheus 文本、CORS 白名单，以及首页渲染、空表单校验和草稿创建交互。

## Nginx 与 SSL

生产反向代理模板和证书配置说明位于 [`deploy/nginx/README.md`](deploy/nginx/README.md)，配置文件为 [`deploy/nginx/xiantu.conf`](deploy/nginx/xiantu.conf)。Nginx 对外提供 80/443，内部转发到回环地址上的 API 和前端；数据库与 Redis 不应暴露公网。


## JWT 认证

当前后端提供 OAuth2 Password Bearer 登录接口：

```bash
curl -X POST http://localhost:8000/auth/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=demo&password=change-me'
```

把返回的 `access_token` 放入请求头访问受保护接口：

```bash
curl http://localhost:8000/api/me \
  -H "Authorization: Bearer <access_token>"
```

认证实现位于 `backend/app/auth.py`：使用 PyJWT 签发和验证 JWT，使用 Argon2 哈希密码。生产环境必须设置高熵 `JWT_SECRET`，缩短 `JWT_EXPIRE_MINUTES`，并将用户、密码哈希和权限迁移到数据库；当前 `demo` 用户仅是模板演示账号。

## Redis 缓存

`backend/app/cache.py` 提供 JSON 序列化的异步 `get/set` 封装，默认 TTL 为 300 秒。示例缓存接口需要 JWT：

```bash
curl -H "Authorization: Bearer <access_token>" http://localhost:8000/api/cache/example
curl -X PUT http://localhost:8000/api/cache/example \
  -H "Authorization: Bearer <access_token>" \
  -H 'Content-Type: application/json' \
  -d '{"value":"hello"}'
```

`/api/health` 会报告 Redis 是否可用。缓存键按用户隔离；生产业务接入时仍需设置键命名空间、TTL、容量上限、脱敏策略，并避免将密码、JWT 或支付数据写入缓存。

## GitHub Actions 一键部署

工作流位于 [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml)，部署说明位于 [`.github/DEPLOYMENT.md`](.github/DEPLOYMENT.md)。Pull Request 会运行后端测试、前端测试、构建和 Compose 校验；推送到 `main` 或手动运行时，会在检查成功后通过 SSH 拉取代码并重建 Compose 服务。

生产部署前需要配置 `DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY`、`DEPLOY_PATH` 和可选的 `DEPLOY_PORT` GitHub Secrets，并在服务器上预先创建 `backend/.env`。


## 商品识别与真实 AI 生图

后端现在提供：

- `POST /api/products/recognize`：上传商品图片，调用 OpenAI 兼容多模态 `chat/completions`，提取商品名称、产地、规格和卖点。
- `POST /api/products`、`GET /api/products`：商品库数据接口。
- `POST /api/generations`：根据商品和风格调用 OpenAI 兼容 `images/generations`，逐张生成素材并保存任务记录。
- `GET /api/assets`：素材库接口。
- `GET /api/generations`：生成记录接口。

在 `backend/.env` 配置真实 AI：

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your-key
OPENAI_VISION_MODEL=gpt-4o-mini
OPENAI_IMAGE_MODEL=gpt-image-1
OPENAI_IMAGE_SIZE=1024x1024
```

也支持任意 OpenAI 兼容厂商，但需要根据厂商文档核对多模态和生图参数。没有 `OPENAI_API_KEY` 时，接口会走 Mock 降级，便于本地联调；生产环境建议关闭 Mock 降级并在 Provider 失败时返回明确错误。

## 数据持久化

当前模板使用 SQLite 作为轻量持久化层，数据库文件默认为 `/data/xiantu.db`，和 Compose 的 `storage` 卷一起保存。数据表包括 `products`、`generation_jobs`、`assets`。后续接入正式 PostgreSQL 时，可以把 `backend/app/storage.py` 替换为 SQLAlchemy/Alembic repository，API 契约不变。

前端已新增：

- `/products` 商品库
- `/assets` 素材库
- `/history` 生成记录

首页生成按钮会自动登录演示账号、创建商品、提交生成任务并刷新联调状态。无 API 服务时仍保留本地预览，不会让工作台崩溃。


## 生产 PostgreSQL 与 Alembic

生产环境不再依赖应用启动时的 `create_all`。`ENVIRONMENT=production` 时，FastAPI 只连接已经完成迁移的数据库；schema 由 Alembic 管理。

关键文件：

- `backend/app/models.py`：SQLAlchemy 模型和 metadata。
- `backend/app/database.py`：将 `postgresql+asyncpg` 转换为 Alembic/SQLAlchemy 使用的 `postgresql+psycopg`。
- `backend/alembic.ini`、`backend/alembic/env.py`：迁移配置。
- `backend/alembic/versions/0001_initial.py`：初始表结构迁移。
- `backend/scripts/migrate_sqlite_to_postgres.py`：旧 SQLite 数据复制到已迁移的 PostgreSQL。

### 新生产环境初始化

先在服务器的 `backend/.env` 设置 PostgreSQL 连接：

```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://xiantu:强密码@postgres:5432/xiantu
DATABASE_FILE=/data/xiantu.db
```

在容器或后端虚拟环境执行：

```bash
alembic upgrade head
alembic current
```

预期显示：

```text
0001_initial (head)
```

### 从旧 SQLite 迁移数据

1. 先备份 SQLite 文件和 PostgreSQL 数据库。
2. 启动 PostgreSQL，但先不要切换 API 流量。
3. 对目标 PostgreSQL 执行结构迁移：

```bash
DATABASE_URL='postgresql+asyncpg://xiantu:密码@postgres:5432/xiantu' \
  alembic upgrade head
```

4. 复制旧数据：

```bash
python backend/scripts/migrate_sqlite_to_postgres.py \
  --sqlite /path/to/xiantu.db \
  --postgres 'postgresql+psycopg://xiantu:密码@postgres:5432/xiantu'
```

5. 校验三张表的行数：

```sql
SELECT 'products' AS table_name, count(*) FROM products
UNION ALL SELECT 'generation_jobs', count(*) FROM generation_jobs
UNION ALL SELECT 'assets', count(*) FROM assets;
```

6. 在 staging 环境验证商品库、素材库、生成记录和新任务写入，再切换生产流量。

迁移脚本默认目标表为空；重复执行会因为主键冲突失败，这是为了避免静默覆盖数据。若需要重跑，应恢复目标库备份或先制定明确的去重/覆盖策略，不要直接删除生产表。

### 日常 schema 变更

开发者修改 `backend/app/models.py` 后生成迁移：

```bash
cd backend
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
```

提交迁移文件和模型变更到同一个 PR。生产发布顺序：备份 → 构建新镜像 → `alembic upgrade head` → 启动/滚动更新 API → `/readyz` 和关键接口检查。

### CI/CD 行为

GitHub Actions 部署阶段现在会：

```bash
docker compose up -d postgres redis
docker compose build api
docker compose run --rm api alembic upgrade head
docker compose up -d --build --remove-orphans
```

迁移失败时工作流停止，不会继续发布 API。正式生产建议给迁移步骤增加数据库备份、staging 验证和 GitHub Environment 审批。

### PostgreSQL 生产注意事项

- 使用强密码或云数据库 IAM/Secret，不要把密码提交到仓库。
- PostgreSQL 只允许应用网络访问，不暴露公网 5432。
- 定期备份并演练恢复，迁移前保留可回滚快照。
- 大表迁移使用可在线执行的分阶段迁移，避免在请求高峰执行锁表 DDL。
- 当前 `storage.py` 使用同步 SQLAlchemy Session；如果生产并发较高，下一步应改成 SQLAlchemy AsyncSession + asyncpg，并为连接池设置上限。


## OpenAI + 通义千问双模型路由

AI 适配器现在支持按顺序尝试多个 OpenAI 兼容 Provider：

```dotenv
AI_PROVIDER_ORDER=openai,qwen
```

OpenAI 配置：

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=...
OPENAI_VISION_MODEL=gpt-4o-mini
OPENAI_IMAGE_MODEL=gpt-image-1
```

千问兼容模式配置：

```dotenv
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=...
QWEN_VISION_MODEL=qwen-vl-plus
QWEN_IMAGE_MODEL=wan2.2-t2i-flash
```

路由策略：

1. 按 `AI_PROVIDER_ORDER` 顺序筛选已配置 API Key 的 Provider。
2. 当前 Provider 超时、HTTP 错误、返回结构错误或 JSON 解析失败时，记录错误并尝试下一个 Provider。
3. 全部 Provider 失败时返回 `AIProviderError`，由 API 层转换为 HTTP 502。
4. 两个 Provider 都没有 Key 时，识别接口返回 Mock 结果，生图接口返回本地素材降级值。
5. 生图对 `gpt-image-1` 不发送 `response_format`，避免该模型拒绝不支持的参数；其他兼容模型默认请求 `b64_json`。

相关实现：[ai.py](backend/app/ai.py)，配置：[config.py](backend/app/config.py)。如果 OpenAI 和千问的图像模型接口参数存在差异，应为对应 Provider 增加专属 payload builder，不要在全局逻辑中硬编码差异。

## Alembic 自动化测试和 CI 验证

新增测试：

- `backend/tests/test_alembic.py`：SQLite 升级、重复升级、回滚到 base、再次升级。
- `backend/tests/test_ai_routing.py`：OpenAI 失败切换千问、图像生成 fallback、无 Key Mock 降级。

GitHub Actions 现在包含两个迁移检查层：

1. `backend-test`：使用临时 SQLite 验证完整迁移生命周期，并运行全部后端测试。
2. `migration-test`：启动 PostgreSQL 16 服务，真实执行 `upgrade head → current → downgrade base → upgrade head`。

这样可以同时发现 SQLite 方言问题和 PostgreSQL 实际执行问题。新增生产迁移时，应继续在 `migration-test` 中验证升级和回滚路径。


## 生产监控、日志和前端状态

### Prometheus + Grafana

FastAPI 已通过 `prometheus-fastapi-instrumentator` 暴露：

```text
GET /metrics
```

默认统计 HTTP 请求总数、响应延迟和状态码等指标。请求日志同时包含 `X-Request-ID`，便于从 Grafana/ELK 追踪单次请求。

启动监控栈：

```bash
export GRAFANA_ADMIN_USER=admin
export GRAFANA_ADMIN_PASSWORD='change-this-in-production'
docker compose -f docker-compose.yml \
  -f deploy/monitoring/docker-compose.monitoring.yml up -d
```

- Prometheus：`127.0.0.1:9090`
- Grafana：`127.0.0.1:3000`
- 数据源已自动指向 Prometheus。

生产环境建议只通过 Nginx/VPN 暴露 Grafana，不要直接开放 3000 和 9090 到公网。

### ELK

应用日志以 JSON 输出到 stdout，Filebeat 读取 Docker container logs，发送到 Logstash，再写入 Elasticsearch，Kibana 用于检索。

启动 ELK：

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/elk/docker-compose.elk.yml up -d
```

- Elasticsearch：内部 `elasticsearch:9200`
- Kibana：`127.0.0.1:5601`
- Logstash Beats：内部/本机 `5044`

ELK 配置文件：

- `deploy/elk/filebeat.yml`
- `deploy/elk/logstash.conf`
- `deploy/elk/docker-compose.elk.yml`

当前示例关闭了 Elasticsearch 安全认证，适合内网 staging。生产环境必须启用认证、TLS、密钥管理和磁盘告警，并为 Elasticsearch 配置持久化卷和快照策略。

### Vue + Pinia

前端已接入 Pinia：

- `frontend/src/stores/app.ts`：全局处理中计数、Toast、错误/成功提示。
- 生成任务和商品识别自动显示全局进度条。
- 页面切换使用淡入淡出和位移动效。
- 卡片、按钮、导航支持 hover/active 动效。
- 生成完成、识别完成和失败状态通过 Toast 反馈。

Pinia 初始化位于 `frontend/src/main.ts`。


## Prometheus 告警、Alertmanager 和钉钉/企业微信

新增：

- `deploy/monitoring/alert_rules.yml`：API 不可用、5xx 比例、P95 延迟告警。
- `deploy/monitoring/alertmanager.yml`：告警分组、重复通知和 resolved 通知配置。
- `deploy/alerting/relay.py`：将 Alertmanager webhook 转成钉钉文本和企业微信 Markdown。
- `deploy/alerting/Dockerfile`：通知转发器镜像。

配置 Webhook：

```bash
export DINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=...'
export WECHAT_WORK_WEBHOOK='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'
```

启动：

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/monitoring/docker-compose.monitoring.yml up -d
```

告警链路：

```text
FastAPI /metrics
  → Prometheus
  → Alertmanager
  → alert-relay
  → 钉钉 / 企业微信
```

生产注意事项：Webhook URL 应通过 Secret 注入，不要提交到 Git；Alertmanager 的 `repeat_interval` 应结合告警等级调整；告警转发器应限制网络访问并增加 webhook 签名校验/重试队列。

## Vue 性能优化

当前前端已完成：

- 路由组件懒加载：`frontend/src/router.ts` 使用动态 `import()`。
- Vite vendor 分包：Vue、Vue Router、Pinia 单独输出 `vue-vendor` chunk。
- CSS code split。
- 生产构建关闭 sourcemap，减少公开静态资源体积。
- `es2020` 构建目标，避免过度转译。
- `optimizeDeps` 预构建核心依赖。
- `index.html` 内联首屏 loading 样式，避免 JS 加载期间白屏。
- 页面切换使用轻量 transition，避免大面积重排。
- 首屏只加载 Home，商品库、素材库和生成记录在访问时加载。

构建后应关注：

```bash
cd frontend
npm run build
```

检查 `dist/assets` 中的 chunk 大小，目标是首屏主包只包含工作台和核心依赖；大型编辑器、图表或上传组件应继续按路由或功能动态加载。生产环境建议通过 Nginx 开启 Brotli/Gzip、长缓存和 immutable hash 资源缓存。


## 全链路压测与多租户 RBAC

压测脚本：[tests/load/k6-full-flow.js](tests/load/k6-full-flow.js)

手动运行 staging 基线：

```bash
API_BASE_URL=https://staging.example.com \
TEST_USERNAME=loadtest \
TEST_PASSWORD='from-secret-manager' \
ENABLE_GENERATION=false \
k6 run tests/load/k6-full-flow.js
```

GitHub Actions 手动压测工作流：

[performance.yml](.github/workflows/performance.yml)

RBAC 设计、租户隔离、角色权限矩阵、迁移顺序和安全测试清单：

[PERFORMANCE_AND_RBAC.md](docs/PERFORMANCE_AND_RBAC.md)

当前仓库先交付了可执行的性能基线和 RBAC 设计规范。RBAC 正式接入前，必须完成 `users/tenants/memberships/audit_logs` 数据迁移、JWT 租户上下文、Repository 租户条件和跨租户安全测试，不能只在前端隐藏菜单来实现权限控制。


## 多租户缓存、AI 配额和越权测试

已加入：

- `backend/app/cache.py`：租户前缀、TTL、SCAN 批量失效。
- `backend/app/quota.py`：Redis Lua 原子预扣、超限 429、失败回滚、按月过期。
- `GET /api/quota`：查看当前租户套餐和月度 AI 用量。
- `backend/tests/test_tenant_cache_quota.py`：缓存隔离和配额测试。
- `backend/tests/test_cross_tenant_security.py`：跨用户/租户资源访问测试。

详细说明：

[TENANT_CACHE_BILLING_SECURITY.md](docs/TENANT_CACHE_BILLING_SECURITY.md)

当前兼容层将 `user:{JWT sub}` 作为租户命名空间。正式多租户 RBAC 接入后，必须替换为经过 membership 校验的 JWT `tenant_id`，不能让客户端直接决定租户身份。


## 正式多租户、Stripe 与用量仪表盘

新增：

- `backend/app/models.py`：tenants、memberships、subscriptions、billing_events，以及业务表 `tenant_id`。
- `backend/app/auth.py`：JWT `tenant_id` 声明和 active membership 校验。
- `backend/app/storage.py`：Repository 强制 `tenant_id` 条件。
- `backend/app/tenancy.py`：租户列表和安全切换 Token。
- `backend/app/billing.py`：Stripe Checkout、Webhook 签名校验和事件幂等。
- `backend/alembic/versions/0002_multitenancy_billing.py`：多租户与账单迁移。
- `frontend/src/views/Billing.vue`：租户切换、套餐和 AI 用量仪表盘。

详细说明：[MULTITENANT_STRIPE_DASHBOARD.md](docs/MULTITENANT_STRIPE_DASHBOARD.md)

Stripe 配置必须通过 Secret 注入：`STRIPE_SECRET_KEY`、`STRIPE_WEBHOOK_SECRET`、`STRIPE_PRICE_PRO`。生产环境不要把支付 Secret 写进前端、镜像或 Git。

Compose 启动前请复制根目录 `.env.example` 为 `.env`，并设置随机的 `POSTGRES_PASSWORD`；Compose 不再包含硬编码数据库密码。


## 商品与素材库 API（最新）

前端工作台已接入真实数据库数据：

- `GET /api/products?q=&limit=&offset=`：当前商家的商品列表与搜索
- `POST /api/products`：创建商品
- `PUT /api/products/{product_id}`：更新商品信息
- `DELETE /api/products/{product_id}`：删除商品
- `GET /api/assets?q=&limit=&offset=`：从生成记录聚合素材库，并返回素材所属商品、生成批次和时间
- 生成流程会先保存/更新商品，再创建生成记录；商品列表和素材库会在生成完成后自动刷新

所有商品和素材接口都要求 `Authorization: Bearer <JWT>`，并按当前用户隔离数据。
