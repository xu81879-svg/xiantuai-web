# Railway 上线部署

本项目采用 **单 Railway Web Service + Railway PostgreSQL**：Vue 在 Docker 构建阶段打包，FastAPI 在运行时同时提供 API 和静态页面。这样不需要分别管理前端域名和跨域配置，适合作为早期 MVP。

## 一键部署前提

1. 将仓库推送到 GitHub。
2. 在 Railway 新建 Project，选择 **Deploy from GitHub Repo**，选择本仓库。
3. Railway 会读取根目录 `railway.toml` 和 `Dockerfile`。
4. 在项目中添加 Railway PostgreSQL 服务。
5. 在 Web Service 的 Variables 中添加下列变量，其中 `DATABASE_URL` 使用 Railway 的服务引用变量：

```dotenv
DATABASE_URL=${{Postgres.DATABASE_URL}}
PGSSLMODE=require
ENVIRONMENT=production
JWT_SECRET=请替换为至少32位随机字符串
JWT_EXPIRE_MINUTES=10080
AUTO_CREATE_SCHEMA=false
SEED_DEMO_USER=false
LOCAL_STORAGE_DIR=/app/data
CORS_ORIGINS=https://你的 Railway 域名
QWEN_API_KEY=请配置为 Railway Secret
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_IMAGE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
QWEN_VISION_MODEL=qwen3-vl-plus
QWEN_IMAGE_MODEL=qwen-image-2.0-pro
QWEN_IMAGE_SIZE=1024*1024
QWEN_TIMEOUT_SECONDS=45
QWEN_MOCK_FALLBACK=false
```

Railway 官方文档说明：PostgreSQL 服务会提供 `DATABASE_URL`，服务之间使用 reference variable 连接；请把 `Postgres` 替换为你实际创建的数据库服务名。如果使用 `ghcr.io/railwayapp-templates/postgres-ssl:18`，保留 `PGSSLMODE=require`。Railway 不会直接执行 `docker-compose.yml`，而是为每个服务分别部署，因此本项目的 Railway 生产入口是根目录 Dockerfile，而不是 Compose。

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

部署后可从本地或 CI 执行健康检查脚本：

```bash
./scripts/railway_healthcheck.sh https://你的-app.up.railway.app
```

脚本只请求 `/api/health` 和 `/readyz`，验证应用进程与数据库连接，不调用千问、不消耗 API 额度。千问商品识别使用 OpenAI 兼容的 Vision Chat 接口，商品生图使用 DashScope 原生 Image 接口；Qwen-Image 返回的临时 URL 会被下载到 `LOCAL_STORAGE_DIR`，避免 24 小时后失效。

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

当前 MVP 将上传图片保存到 `LOCAL_STORAGE_DIR`。Railway 默认容器文件系统不是长期对象存储，因此上线时建议给 Web Service 添加 Volume，并将挂载路径设置为 `/app/data`。后续接入 S3 / Cloudflare R2 / 阿里云 OSS 时，只需要替换 `recognize_product` 的文件保存实现，数据库中的 `image_url` 契约保持不变。

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
