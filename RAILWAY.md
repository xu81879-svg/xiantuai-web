# Railway 上线部署

本项目采用 **单 Railway Web Service + Railway PostgreSQL**：Vue 在 Docker 构建阶段打包，FastAPI 在运行时同时提供 API 和静态页面。这样不需要分别管理前端域名和跨域配置，适合作为早期 MVP。

## 一键部署前提

1. 将仓库推送到 GitHub。
2. 在 Railway 新建 Project，选择 **Deploy from GitHub Repo**，选择本仓库。
3. Railway 会读取根目录 `railway.toml` 和 `Dockerfile`。
4. 在项目中添加 Railway PostgreSQL 服务。
5. 在 Web Service 的 Variables 中添加下列变量，其中 `DATABASE_URL` 必须使用 Railway 的服务引用变量：在 Web Service 中点击 **Add Variable → Add Reference**，选择实际 PostgreSQL 服务的 `DATABASE_URL`。不要把 `${{Postgres.DATABASE_URL}}` 当作普通文本粘贴，也不要手动添加引号；如果 PostgreSQL 服务名称不是 `Postgres`，不能继续使用这个示例名称。

```dotenv
# DATABASE_URL 请在 Railway Web Service Variables 中使用 Add Reference 设置
PGSSLMODE=require
ENVIRONMENT=production
JWT_SECRET=请替换为至少32位随机字符串
JWT_EXPIRE_MINUTES=10080
AUTO_CREATE_SCHEMA=false
SEED_DEMO_USER=false
LOCAL_STORAGE_DIR=/app/data
CORS_ORIGINS=https://你的 Railway 域名
# 可选但生产多 worker/多副本推荐：添加 Redis 服务并用 Add Reference 设置
REDIS_URL=${{Redis.REDIS_URL}}
# 生产注册必须配置 SMTP；凭据请使用 Railway Secret，不要写入 Git
SMTP_HOST=你的 SMTP 主机
SMTP_PORT=587
SMTP_USERNAME=你的 SMTP 用户名
SMTP_PASSWORD=请配置为 Railway Secret
SMTP_FROM=鲜图 AI <no-reply@你的域名>
SMTP_STARTTLS=true
SMTP_TIMEOUT_SECONDS=10
QWEN_API_KEY=请配置为 Railway Secret
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MULTIMODAL_MODEL=qwen3-vl-plus
QWEN_IMAGE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
QWEN_VISION_MODEL=qwen3-vl-plus
QWEN_IMAGE_MODEL=qwen-image-2.0-pro
QWEN_IMAGE_SIZE=1024*1024
QWEN_TIMEOUT_SECONDS=120
QWEN_READ_TIMEOUT_SECONDS=120
QWEN_MOCK_FALLBACK=false
PAYPAL_BASE_URL=https://api-m.paypal.com
PAYPAL_CLIENT_ID=请配置为 Railway Secret
PAYPAL_CLIENT_SECRET=请配置为 Railway Secret
PAYPAL_WEBHOOK_ID=请配置为 Railway Secret
PAYPAL_CURRENCY=USD
PAYPAL_BRAND_NAME=鲜图 AI
PUBLIC_APP_URL=https://你的 Railway 域名
PAYPAL_MOCK_MODE=false
PAYPAL_TIMEOUT_SECONDS=30
```

Railway 官方文档说明：PostgreSQL 服务会提供 `DATABASE_URL`，服务之间使用 reference variable 连接；请在变量面板中选择实际创建的数据库服务，不要手工填写服务名。Web Service 只需要读取 `DATABASE_URL`，不需要额外添加 `POSTGRES_USER`、`POSTGRES_PASSWORD` 或 `POSTGRES_DB`；这些是数据库容器的初始化变量，不能替代应用连接串。如果使用 `ghcr.io/railwayapp-templates/postgres-ssl:18`，保留 `PGSSLMODE=require`。

应用会自动去除 `DATABASE_URL` 两侧意外出现的单引号或双引号，以兼容 Railway 面板将值显示或注入为带引号字符串；但如果生产环境没有解析出 `DATABASE_URL`，应用现在会明确拒绝启动，不再静默回退到 SQLite。这样可以避免服务看似健康但重启后丢失用户数据。

## 首次发布

容器启动命令会先执行：

```bash
alembic upgrade head
```

然后启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Railway 使用 `/readyz` 作为健康检查。首次部署成功后，在 Networking 中生成 Public Domain，即可访问首页。

数据库服务创建完成后，Web Service 至少需要配置：

```dotenv
DATABASE_URL=${{你的 PostgreSQL 服务名.DATABASE_URL}}
PGSSLMODE=require
```

发布日志应依次看到 `alembic upgrade head` 成功、Uvicorn 启动成功，随后 `/readyz` 返回 `{"status":"ready"}`。如果迁移失败，先检查 Web Service 与数据库服务是否位于同一个 Railway Project，以及 reference variable 中的服务名是否完全一致。

当前会员升级采用 PayPal 一次性额度包，不做自动续费：尝鲜包 20 次、专业包 100 次、商家包 300 次。生产环境需要创建 PayPal REST App，配置 Client ID、Client Secret 和 Webhook ID，并将 `PUBLIC_APP_URL` 设置为真实 HTTPS 域名。代码会在生产环境拒绝 Mock 与 Sandbox 下单/入账，只允许准确的 PayPal Live API 主机；额度面板显示后端报告的真实支付模式、余额和订单历史。前端通过 PayPal JavaScript SDK 嵌入按钮，后端仍负责创建订单、捕获订单、严格核对订单归属/金额/币种和幂等入账；Webhook 用于补偿用户关闭页面后的异步支付完成事件。

生产注册需要配置 SMTP 主机、发件地址和 `PUBLIC_APP_URL`；验证令牌 30 分钟过期、数据库只保存令牌哈希。未完成邮箱验证的账户不能登录，也不会获得初始额度；没有 SMTP 配置时注册会返回 503，不会静默跳过验证。迁移会把已有账户标记为已验证并保留其当前余额。Redis 配置可让登录、注册/重发验证和高成本图片接口限流跨进程共享；没有 Redis 时会回退到进程内限流，因此生产多 worker/多副本应配置共享 Redis，并确认 Railway 代理可信客户端地址由 Uvicorn 正确传递。

PayPal Developer Dashboard 的生产 Webhook URL 必须设置为：

```text
https://你的 Railway 公共域名/api/webhooks/paypal
```

至少勾选 `PAYMENT.CAPTURE.COMPLETED` 事件，并将该 Webhook 生成的 ID 填入 `PAYPAL_WEBHOOK_ID`。上线核验顺序为：`GET /readyz` 返回 `{"status":"ready"}`；`GET /api/billing/paypal/config`（需登录）返回 `mode: "live"`、`enabled: true` 且 `client_id` 非空；PayPal Dashboard 中的 Webhook 状态为已启用；最后在确认 Live 配置后使用受控的小额订单检查回调。不要把 Client Secret 或 Webhook ID 写入前端或 Git。

部署后可从本地或 CI 执行健康检查脚本：

```bash
./scripts/railway_healthcheck.sh https://你的-app.up.railway.app
```

脚本只请求 `/api/health` 和 `/readyz`，验证应用进程与数据库连接，不调用千问、不消耗 API 额度。千问商品识别使用包含“文字提示词 + 商品图片”的 OpenAI 兼容多模态 Chat 接口，默认模型为 `qwen3-vl-plus`；服务会在发送前将图片最长边压缩到 1600px，并对瞬时网络超时最多重试 2 次。商品生图使用 DashScope 原生 Image 接口，默认模型为 `qwen-image-2.0-pro`；Qwen-Image 返回的临时 URL 会被下载到 `LOCAL_STORAGE_DIR`，避免 24 小时后失效。`QWEN_MULTIMODAL_MODEL` 优先于 `QWEN_VISION_MODEL`，便于后续切换视觉模型而不改代码。

环境变量完整性检查使用 `scripts/check_railway_env.sh`。它不会打印 Secret 值，也不会自动创建账户或 PayPal 订单：

```bash
# 检查本地变量文件是否缺项、是否仍有占位值，以及生产安全开关
./scripts/check_railway_env.sh --file railway.env.example

# 检查线上健康状态
./scripts/check_railway_env.sh --url https://你的-app.up.railway.app

# 使用已有测试账户检查线上 PayPal runtime config；密码只通过环境变量传入
RAILWAY_CHECK_EMAIL='you@example.com' \
RAILWAY_CHECK_PASSWORD='你的密码' \
./scripts/check_railway_env.sh --url https://你的-app.up.railway.app
```

线上检查可以确认 `/readyz`、`/api/health` 以及登录后的 `/api/billing/paypal/config`；它不能直接读取 Railway Secret 原文，只能根据应用运行时返回的 `enabled` 状态判断 PayPal 凭据是否生效。

连接 Railway 之前，可以使用 `scripts/check_railway_local.py` 在本地预检 env 文件格式、未解析的 Railway 引用、生产 SQLite 回退、PostgreSQL URL 和 SQLAlchemy 连接池配置。脚本不会访问 Railway、不会建立数据库连接，也不会输出密码或连接串：

```bash
python3 scripts/check_railway_local.py --file railway.env
```

也可以检查当前进程环境变量：

```bash
DATABASE_URL='"postgresql://user:password@host/db"' \
ENVIRONMENT=production PGSSLMODE=require \
AUTO_CREATE_SCHEMA=false SEED_DEMO_USER=false \
python3 scripts/check_railway_local.py --allow-missing-file
```

预检通过后，再使用 Railway Dashboard 的 **Add Reference** 或 Railway CLI 绑定真实 `DATABASE_URL`。示例中的数据库 URL 只用于格式演示，不要提交真实凭据。

完整上线烟雾测试：

```bash
./scripts/railway_smoke_test.sh https://你的-app.up.railway.app
```

脚本会创建一个临时测试账户，验证登录、当前用户、商品创建/搜索/更新/删除、模板中心、帮助中心、生成记录和素材库。默认会执行一次真实生成，因此如果已配置千问会消耗一次生图额度，并会保留一条生成记录；只验证非生图接口时执行：

```bash
SMOKE_SKIP_GENERATION=true ./scripts/railway_smoke_test.sh https://你的-app.up.railway.app
```

如需使用已有账户而不创建新账户：

```bash
SMOKE_AUTH_MODE=login SMOKE_EMAIL=you@example.com SMOKE_PASSWORD='你的密码' ./scripts/railway_smoke_test.sh https://你的-app.up.railway.app
```

## 文件上传持久化

当前 MVP 将上传图片保存到 `LOCAL_STORAGE_DIR`。Railway 默认容器文件系统不是长期对象存储，因此必须给 Web Service 添加 Volume，并将挂载路径设置为 `/app/data`，与变量值一致。API 与独立 Celery Worker/多副本必须读写同一持久存储；Railway Volume 不是跨服务共享对象存储，多实例时应迁移到 S3/Cloudflare R2/OSS。前端现在会对失效图片显示明确占位图，但这只改善展示：挂载 Volume 无法恢复已丢失的旧文件，旧图片需从备份恢复或重新生成。当前真实生成记录只保存实际落盘的 Qwen 图片，不再拿通用水果图补成“五张成品”。

## 亚洲客户默认策略

- 默认界面语言为简体中文 `zh-CN`。
- 默认时区为 `Asia/Shanghai`，用户表保留 `locale` 和 `timezone` 字段，便于后续扩展日本、韩国、东南亚地区。
- 商品信息、卖点、生成用途均使用 UTF-8，数据库字段采用 Unicode 字符串。
- 前端提供窄屏适配，可在常见亚洲移动浏览器中访问。
- 货币、税费、支付和短信暂不硬编码，后续按国家/地区拆分配置。

## 发布前检查

```bash
# 本地数据库迁移
cd backend
DATABASE_URL=sqlite:///./release-check.db AUTO_CREATE_SCHEMA=false alembic upgrade head
DATABASE_URL=sqlite:///./release-check.db AUTO_CREATE_SCHEMA=false python -m compileall app

# 前端构建
cd ../frontend
npm ci
npm run build

# 根目录容器构建
cd ..
docker build -t xiantu-ai-mvp .
```

生产环境不要开启 `SEED_DEMO_USER`，不要使用默认 `JWT_SECRET`，不要把真实密钥提交到 Git。
