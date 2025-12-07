# Pylon

Pylon 是一个 HTTP API 代理服务，提供 API Key 认证、多维度限流、优先级队列、统计分析等功能。

## 功能特性

- **API 代理**：透明代理所有 HTTP 请求到下游 API，支持 SSE 流式响应
- **API Key 认证**：为原始 API 添加认证层，支持 Key 的创建、吊销、刷新
- **多维度限流**：支持全局/用户/API 三个维度的并发数和请求频率限制
- **优先级队列**：当并发达到上限时，请求进入优先级队列等待，高优先级可抢占
- **SSE 限流**：SSE 连接独立计数，消息与普通请求共享频率配额
- **统计分析**：记录请求日志，提供按用户/API 的统计报告，支持 JSON/CSV/HTML 导出
- **管理界面**：Vue 3 + Element Plus 构建的 Web 管理界面
- **配置热更新**：策略配置支持热更新，无需重启服务

## 快速开始

### Docker 部署（推荐）

```bash
cd docker
docker compose up -d
```

- 前端界面：http://localhost:5173
- 代理端口：http://localhost:8000
- 管理端口：http://localhost:8001

默认密码：`admin`

详细说明参考 [Docker 部署指南](docker/README.md)。

### 本地开发

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 创建配置文件

复制示例配置并修改：

```bash
cp config.example.yaml config.yaml
```

生成管理员密码哈希：

```bash
python -m pylon hash-password
```

将生成的哈希值填入 `config.yaml` 的 `admin.password_hash` 字段。

#### 3. 启动服务

```bash
python -m pylon -c config.yaml
```

服务启动后：
- 代理端口：http://localhost:8000
- 管理端口：http://localhost:8001

首次启动时，策略配置（Policy）会自动初始化为默认值并存入数据库。

#### 4. 创建 API Key

```bash
# 登录获取 Token
TOKEN=$(curl -s -X POST http://localhost:8001/login \
  -H "Content-Type: application/json" \
  -d '{"password": "your-password"}' | jq -r '.token')

# 创建 API Key
curl -X POST http://localhost:8001/api-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"description": "My App"}'
```

#### 5. 使用代理

```bash
curl http://localhost:8000/your-api-endpoint \
  -H "Authorization: Bearer sk-your-api-key"
```

## 前端界面

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173

## 文档

- [设计文档](docs/design.md) - 详细的架构设计、数据模型、限流策略等
- [使用示例](docs/demo.md) - 完整的手动测试流程和使用指南
- [Docker 部署](docker/README.md) - Docker 镜像构建和部署指南

## 项目结构

```
pylon/
├── pylon/                 # 后端代码
│   ├── api/               # API 路由
│   ├── models/            # 数据模型
│   ├── services/          # 业务服务
│   └── utils/             # 工具函数
├── frontend/              # Vue 3 前端
│   └── src/
│       ├── api/           # API 封装
│       ├── views/         # 页面组件
│       ├── router/        # 路由
│       └── stores/        # 状态管理
├── docker/                # Docker 相关文件
│   ├── Dockerfile
│   ├── docker-compose.yaml
│   └── README.md
├── tests/                 # 测试
│   ├── unit/              # 单元测试
│   ├── e2e/               # 端到端测试
│   └── mock_server/       # Mock 服务器
├── docs/                  # 文档
├── config.example.yaml    # 静态配置示例
├── policy.example.yaml    # 策略配置示例
└── requirements.txt       # Python 依赖
```

## 配置说明

Pylon 的配置分为两部分：

### 静态配置（config.yaml）

需要重启服务才能生效的配置，包含敏感信息：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `server.proxy_port` | 代理服务端口 | 8000 |
| `server.admin_port` | 管理服务端口 | 8001 |
| `server.host` | 监听地址 | 0.0.0.0 |
| `database.url` | 数据库连接 URL | sqlite+aiosqlite:///./data/pylon.db |
| `admin.password_hash` | 管理员密码哈希 | - |
| `admin.jwt_secret` | JWT 签名密钥 | - |
| `admin.jwt_expire_hours` | JWT 过期时间(小时) | 24 |
| `logging.level` | 日志级别 | INFO |

### 策略配置（Policy）

存储在数据库中，支持热更新，可通过管理界面或 API 修改：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `downstream.base_url` | 下游 API 地址 | - |
| `downstream.timeout` | 下游请求超时(秒) | 30 |
| `rate_limit.global.max_concurrent` | 全局最大并发 | 50 |
| `rate_limit.global.max_requests_per_minute` | 全局每分钟请求数 | 500 |
| `rate_limit.global.max_sse_connections` | 全局最大 SSE 连接 | 20 |
| `rate_limit.default_user.max_concurrent` | 用户默认最大并发 | 4 |
| `rate_limit.default_user.max_requests_per_minute` | 用户默认每分钟请求数 | 60 |
| `rate_limit.default_user.max_sse_connections` | 用户默认最大 SSE 连接 | 2 |
| `queue.max_size` | 队列最大长度 | 100 |
| `queue.timeout` | 队列等待超时(秒) | 30 |
| `sse.idle_timeout` | SSE 空闲超时(秒) | 60 |
| `data_retention.days` | 日志保留天数 | 30 |
| `data_retention.cleanup_interval_hours` | 清理间隔(小时) | 24 |

策略配置支持通过管理界面导入/导出 YAML 文件，参考 [policy.example.yaml](policy.example.yaml)。

## 技术栈

**后端**：
- Python 3.12+
- FastAPI
- SQLAlchemy (async)
- SQLite / PostgreSQL

**前端**：
- Vue 3
- Element Plus
- Vite
- Pinia
- Axios

## 测试

```bash
# 运行单元测试
python -m pytest tests/unit/ -v

# 运行所有测试
python -m pytest tests/ -v
```

## License

MIT
