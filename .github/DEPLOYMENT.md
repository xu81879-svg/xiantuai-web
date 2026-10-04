# 生产数据库与环境变量迁移方案

## 当前状态

项目使用 Railway 根目录 `Dockerfile` 和 `railway.toml` 部署单一 Web Service，前端在镜像构建阶段编译，FastAPI 在运行时提供页面和 API。生产数据库使用 Railway PostgreSQL；数据库结构由 Alembic 管理，当前初始迁移为 `0001_initial`。

GitHub Actions 负责提交门禁，不把生产密钥写进 Git。Railway 负责从 `main` 构建和发布服务；在 Railway 项目中开启 GitHub 仓库的自动部署，或使用 Railway Dashboard 手动部署经过 Actions 检查的 `main`。

## Railway 服务配置

在同一个 Railway Project 中创建：

1. **PostgreSQL** 服务；
2. **Web Service**，连接 GitHub 仓库 `xu81879-svg/xiantuai-web`，分支为 `main`；
3. 在 Web Service 中配置 Volume，挂载到 `/app/data`，用于 MVP 阶段的上传文件临时持久化。正式生产建议迁移到 S3、Cloudflare R2 或阿里云 OSS。

`railway.toml` 已声明根目录 Dockerfile、`/readyz` 健康检查和启动迁移命令。单实例 MVP 可以继续使用启动前 `alembic upgrade head`；扩展到多实例前，应改成 Railway 的单次 pre-deploy migration，避免多个副本同时执行迁移。

## 生产环境变量

在 Railway Web Service 的 Variables 中设置以下变量。`DATABASE_URL` 应使用 Railway Reference Variable，而不是复制数据库密码：

| 变量 | 生产值 | 说明 |
|---|---|---|
| `ENVIRONMENT` | `production` | 启用生产配置 |
| `DEBUG` | `false` | 禁止生产调试模式 |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | 自动引用 PostgreSQL 连接串 |
| `JWT_SECRET` | 由密码管理器生成的 32+ 字符随机值 | 只存 Railway Secret |
| `JWT_EXPIRE_MINUTES` | `10080` 或更短 | 当前默认 7 天；高安全场景建议缩短 |
| `AUTO_CREATE_SCHEMA` | `false` | 生产禁止应用自行建表 |
| `SEED_DEMO_USER` | `false` | 生产禁止创建演示账号 |
| `LOCAL_STORAGE_DIR` | `/app/data` | 仅在已配置 Volume 时使用 |
| `CORS_ORIGINS` | `https://<railway-domain>` | 只允许真实前端来源，不使用 `*` |
| `OPENAI_BASE_URL` | 按实际 Provider 设置 | 可选 |
| `OPENAI_API_KEY` | Railway Secret | 可选，不提交 Git |
| `OPENAI_VISION_MODEL` | 按实际 Provider 设置 | 可选 |
| `OPENAI_IMAGE_MODEL` | 按实际 Provider 设置 | 可选 |

生产变量模板见根目录 `railway.env.example`。其中的中文占位值只能复制后替换，不能直接作为生产值。

## 数据库迁移顺序

### 首次上线

1. 创建 Railway PostgreSQL，并确认服务状态为 healthy。
2. 配置 `DATABASE_URL=${{Postgres.DATABASE_URL}}`、`AUTO_CREATE_SCHEMA=false` 和 `SEED_DEMO_USER=false`。
3. 先在 staging 环境执行 `alembic upgrade head`，再检查 `alembic current` 是否为 `0001_initial`。
4. 验证注册、登录、商品创建、商品列表、素材库和生成记录接口。
5. 通过 Railway 发布 Web Service；启动过程会执行迁移并通过 `/readyz` 后接收流量。

### 日常 schema 变更

1. 修改 SQLAlchemy 模型并生成新的 Alembic revision。
2. 在 GitHub Actions 的 PostgreSQL 16 服务中执行 `upgrade → current → downgrade base → upgrade head`。
3. 合并到 `main` 后，先备份生产 PostgreSQL，再让 Railway 发布新镜像。
4. 观察 `/readyz`、错误率和数据库连接数，确认新 revision 已应用。
5. 若应用回滚，先确认迁移是向后兼容的；不要直接删除生产表或使用 `downgrade` 作为未经验证的回滚手段。

## 备份与恢复

生产迁移前必须保留 PostgreSQL 备份或快照。恢复演练至少覆盖：用户、商品、生成记录和素材索引。上传文件不应只依赖容器本地文件系统；切换对象存储后，数据库继续保存 `image_url` 和素材元数据。

## GitHub Actions

`.github/workflows/ci.yml` 在 Pull Request 和 `main` push 上运行三项检查：后端 pytest、前端生产构建、PostgreSQL Alembic 生命周期验证。当前工作流不会读取生产密钥，也不会直接执行生产迁移；生产迁移由 Railway 发布流程执行，避免 CI 访问生产数据库。

如果要把 Railway 部署也纳入 Actions，必须先在 GitHub Actions Secrets 中配置 Railway 官方要求的项目级凭据，并增加受保护环境审批。未配置这些凭据前，不应添加会必然失败的自动部署 job。
