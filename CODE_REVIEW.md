# 鲜图 AI：静态代码检查报告

**检查时间：** 2026-10-03  
**检查范围：** 当前项目目录中的 `README.md`、`docker-compose.yml`

> 当前目录只包含上述两个文件；`backend/`、`frontend/`、`ops/` 目录均不存在，也没有 Git 仓库元数据。因此本次无法运行 `pytest`、构建镜像、启动服务，或审查 FastAPI / Vue / Pipeline 的实际实现。

## 结论摘要

| 优先级 | 问题 | 影响 |
|---|---|---|
| P0 | Compose 所引用的 `backend/` 构建上下文与环境文件不存在 | 当前项目无法构建或启动 |
| P1 | README 要求配置 `backend/.env`，但 Compose 固定读取 `.env.example` | 真实 AI、存储等运行配置很可能不生效 |
| P1 | Redis 仅以 `service_started` 作为依赖条件 | API / Worker 启动时可能因 Redis 尚未就绪而失败或重试 |
| P2 | PostgreSQL、Redis 端口直接暴露到宿主机 | 非纯本地环境下扩大未授权访问面 |
| P2 | README 将 `docker compose down -v` 作为升级建议 | 容易误删数据库与对象存储卷中的数据 |

## 详细发现

### P0：Compose 的必要目录与文件缺失

**证据**

- `docker-compose.yml:2`：`build: ./backend`
- `docker-compose.yml:3`：`env_file: ./backend/.env.example`
- `README.md:7–9`：启动流程依赖 `backend/` 与 `frontend/`
- 当前目录树只有 `README.md` 与 `docker-compose.yml`，未找到 `backend/`、`frontend/`、`ops/`。

**影响**

Docker Compose 无法取得 `./backend` 作为镜像构建上下文，也无法读取环境文件；即使 Docker 已安装，项目也不能按 README 的步骤启动。业务代码、测试和 Dockerfile 均不可用，因此不能评估鉴权、额度扣减、任务幂等性、AI 网关降级或图像处理安全性。

**建议修复**

1. 将完整的 `backend/`、`frontend/`、`ops/` 目录及必要的 `Dockerfile`、测试文件纳入同一仓库或共享工作区。
2. 若代码位于另一个仓库，补充正确的 Git 地址、子模块配置或构建上下文路径。
3. 在 CI 中增加最基础的前置校验：确认构建上下文、`env_file`、挂载源文件存在后再执行构建。

### P1：运行配置文件与 README 不一致

**证据**

- `README.md:7` 指示执行：`cp backend/.env.example backend/.env`。
- `README.md:25–34` 指示将真实 AI 厂商配置写入 `backend/.env`。
- `docker-compose.yml:3` 却固定为：`env_file: ./backend/.env.example`。

**影响**

用户依照 README 创建并修改 `backend/.env` 后，容器仍读取 `.env.example`。因此 `OPENAI_API_KEY`、`AI_*_CHAIN`、S3、Sentry 等运行设置可能完全没有进入容器，导致服务仍使用 Mock 或无法连接真实服务。

**建议修复**

将 Compose 调整为读取实际运行文件：

```yaml
x-backend: &backend
  build: ./backend
  env_file: ./backend/.env
```

并在版本控制中保留 `backend/.env.example`，通过 `.gitignore` 忽略 `backend/.env`。CI / 部署环境应改为由密钥管理系统或部署平台注入变量，不能提交真实密钥。

### P1：Redis 未做就绪检查

**证据**

- `docker-compose.yml:25–27` 的 `redis` 服务没有 `healthcheck`。
- `docker-compose.yml:12` 只使用 `redis: { condition: service_started }`。

**影响**

`service_started` 只表示 Redis 容器进程已启动，并不代表其已可接受连接。API 或 Arq Worker 在 Redis 尚未就绪时可能出现连接失败、启动抖动或任务注册失败。

**建议修复**

为 Redis 添加健康检查，并要求后端服务等待健康状态：

```yaml
redis:
  image: redis:7
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 3s
    timeout: 3s
    retries: 20

# x-backend 内
 depends_on:
   redis:
     condition: service_healthy
```

应用自身仍应保留有限重试和指数退避，因为编排层的依赖顺序不能替代运行时容错。

### P2：数据库与缓存服务无条件暴露端口

**证据**

- `docker-compose.yml:19`：`"5432:5432"`
- `docker-compose.yml:27`：`"6379:6379"`

**影响**

在服务器、共享开发机或云主机中，这会把 PostgreSQL 与 Redis 直接暴露给宿主机网络。Redis 未配置认证；若主机防火墙或安全组配置不当，可能被未授权访问。

**建议修复**

默认删除两个 `ports` 声明，让服务仅在 Compose 内部网络可访问；需要本机调试时再使用开发覆盖文件，或限制到回环地址：

```yaml
ports:
  - "127.0.0.1:5432:5432"
```

生产环境还应使用强密码、最小网络暴露与受管数据库/缓存服务。

### P2：升级操作说明存在数据删除风险

**证据**

- `README.md:11` 建议升级代码后执行 `docker compose down -v`。
- `docker-compose.yml:49` 定义了 `pg` 与 `storage` 命名卷。

**影响**

`down -v` 会删除命名卷，因而清空 PostgreSQL 数据与本地对象存储文件。对于含用户任务、额度、支付记录或成品文件的系统，这一命令不应作为常规升级步骤。

**建议修复**

- 常规重建使用：`docker compose up -d --build`。
- 仅在明确要重置**开发测试数据**时使用 `docker compose down -v`，并在 README 中突出删除范围与不可恢复风险。
- 用 Alembic 或等价迁移工具处理模式演进，替代删除数据库重建表。

## 验证情况与后续检查清单

| 检查项 | 状态 | 原因 |
|---|---|---|
| 项目目录清点 | 已完成 | 仅发现两个配置/文档文件 |
| Git 变更检查 | 未执行 | 当前目录不是 Git 仓库 |
| `docker compose config` | 未执行 | 环境未安装 Docker CLI |
| 后端单元测试 | 未执行 | `backend/` 与测试代码缺失 |
| 前端构建 / 类型检查 | 未执行 | `frontend/` 缺失 |
| 安全与业务逻辑审查 | 未执行 | 源代码缺失 |

## 建议的下一步

补充完整项目源代码后，建议依次执行：

```bash
cd backend && pytest
cd ../frontend && npm ci && npm run build
# Docker 可用的环境中
docker compose config
docker compose up --build
```

随后可继续进行 API 鉴权、支付回调幂等性、额度并发扣减、任务重试/退款、对象存储访问控制和依赖漏洞扫描的代码级审查。
