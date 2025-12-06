# Pylon - HTTP API Proxy 设计文档

## 概述

Pylon 是一个 HTTP API 代理服务，用于代理南向 API 并提供认证、限流、统计等功能。

### 核心功能

1. **API 代理**：透传代理南向 API，支持 SSE
2. **API Key 认证**：原始 API 无需认证，代理层添加认证
3. **限流策略**：支持全局和用户级别的多维度限流
4. **用户行为统计**：实时查看，支持导出报告

### 技术栈

- **后端**：Python + FastAPI
- **前端**：Vue 3 + Element Plus
- **数据库**：SQLite（可切换 PostgreSQL）
- **限流存储**：内存（单机部署）

---

## 架构设计

### 系统架构图

```
+------------------+       +------------------+       +------------------+
|                  |       |                  |       |                  |
|  Client Request  +------>+  Pylon Proxy     +------>+  Downstream API  |
|                  |       |  (Port 8000)     |       |                  |
+------------------+       +--------+---------+       +------------------+
                                    |
                           +--------+---------+
                           |                  |
                           |    SQLite DB     |
                           |                  |
                           +--------+---------+
                                    |
+------------------+       +--------+---------+
|                  |       |                  |
|   Admin Web UI   +------>+  Pylon Admin     |
|   (Vue 3)        |       |  (Port 8001)     |
+------------------+       +------------------+
```

### 双端口架构

| 端口 | 用途 | 说明 |
|------|------|------|
| 8000 | 代理服务 | 透传所有请求到 Downstream API |
| 8001 | 管理服务 | API Key 管理、统计、配置等 |

**优点**：
- 路径完全隔离，零冲突风险
- 可对管理端口单独配置访问控制（如只允许内网访问）
- 代理逻辑简单，无需判断路径

### 健康检查

代理端口提供健康检查接口（无需认证）：

```
GET /health

Response:
{
  "status": "ok",
  "downstream": "ok",       // 或 "error"
  "queue_size": 5,          // 当前队列长度
  "active_connections": 10  // 当前并发数
}
```

用途：
- 负载均衡器探活
- 监控系统集成

### 请求处理流程

```
                              Request
                                 |
                                 v
                    +------------------------+
                    |  Parse API Key         |
                    |  (Authorization Header)|
                    +------------------------+
                                 |
                                 v
                    +------------------------+
                    |  Validate API Key      |
                    |  - Exists?             |
                    |  - Not expired?        |
                    |  - Not revoked?        |
                    +------------------------+
                                 |
                          +------+------+
                          |             |
                       Invalid        Valid
                          |             |
                          v             v
                     401 Error   +------------------------+
                                 |  Check User Rate Limit |
                                 +------------------------+
                                            |
                                     +------+------+
                                     |             |
                                  Exceeded       OK
                                     |             |
                                     v             v
                                429 Error  +------------------------+
                                "User      |  Check Global Rate     |
                                 limit"    |  Limit                 |
                                           +------------------------+
                                                      |
                                               +------+------+
                                               |             |
                                            Exceeded       OK
                                               |             |
                                               v             v
                                          429 Error   +------------------------+
                                          "System     |  Forward to            |
                                           busy"      |  Downstream API        |
                                                      +------------------------+
                                                                 |
                                                                 v
                                                      +------------------------+
                                                      |  Log Request           |
                                                      |  Return Response       |
                                                      +------------------------+
```

---

## 数据模型

### API Key

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string (UUID) | 主键，用于日志、配置等引用 |
| key_hash | string | API Key 的加密哈希值 |
| key_prefix | string | API Key 前缀（如 `sk-...`），用于识别 |
| description | string | 简短描述 |
| priority | enum | 优先级：`high` / `normal` / `low`，默认 `normal` |
| created_at | datetime | 创建时间 |
| expires_at | datetime | 过期时间（可为空，表示永不过期） |
| revoked_at | datetime | 吊销时间（可为空） |
| rate_limit_config | JSON | 该用户的限流配置（可为空，使用默认值） |

**API Key 存储方式**：
- 实际 Key 内容使用 SHA-256 哈希后存储
- 验证时：对请求中的 Key 进行哈希，与数据库比对
- Key 只在创建时返回一次，之后无法查看原始内容

### 请求日志

| 字段 | 类型 | 说明 |
|------|------|------|
| id | integer | 主键，自增 |
| api_key_id | string | 关联的 API Key ID |
| api_identifier | string | API 标识（如 `POST /v1/chat/completions`） |
| request_path | string | 请求路径 |
| request_method | string | HTTP 方法 |
| response_status | integer | 响应状态码 |
| request_time | datetime | 请求时间 |
| response_time_ms | integer | 响应耗时（毫秒） |
| client_ip | string | 客户端 IP |
| is_sse | boolean | 是否为 SSE 连接 |
| sse_message_count | integer | SSE 消息数（非 SSE 为 0） |

---

## 限流策略

### 限流维度

| 维度 | 适用范围 | 说明 |
|------|---------|------|
| 普通 HTTP 并发数 | 全局 / 用户 | 同时处理的普通请求数 |
| 请求频率 | 全局 / 用户 / API | 普通请求 + SSE 消息数，每分钟 |
| SSE 并发连接数 | 全局 / 用户 | 同时保持的 SSE 连接数 |

### 限流检查顺序

**三者独立检查，任一超限即拒绝**：

```
Request
   |
   v
+------------------+
| Check User Limit | ---> Exceeded ---> 429 "Your request limit exceeded"
+------------------+
   | OK
   v
+------------------+
| Check API Limit  | ---> Exceeded ---> 429 "API rate limit exceeded"
+------------------+
   | OK
   v
+------------------+
| Check Global     | ---> Exceeded ---> 429 "System busy, try later"
| Limit            |
+------------------+
   | OK
   v
+------------------+
| Concurrency      | ---> Full ---> Enter Queue
| Check            |
+------------------+
   | Available
   v
Forward Request
```

### 请求队列

当并发数达到上限时，请求进入优先级队列等待处理。

#### 队列机制

```
+------------------+
|  Priority Queue  |
|------------------|
| [high] req1      |  <-- 高优先级在前
| [high] req2      |
| [normal] req3    |
| [normal] req4    |
| [low] req5       |
+------------------+
         |
         v
   当有空闲并发时
   从队头取出处理
```

#### 队列规则

- **触发时机**：仅当并发数已满时才排队，未满时直接处理
- **排序规则**：按优先级排序，同优先级按到达时间（FIFO）
- **队列上限**：默认 100，满时高优先级可挤掉低优先级
- **排队超时**：默认 30 秒，超时返回 504 Gateway Timeout
- **被抢占处理**：低优先级请求被挤出时，返回 503 "Request preempted by higher priority"

#### 优先级定义

| 优先级 | 说明 |
|--------|------|
| `high` | 最高优先级，可抢占其他请求 |
| `normal` | 默认优先级 |
| `low` | 最低优先级，可被抢占 |

#### 配置示例

```yaml
queue:
  max_size: 100        # 队列上限
  timeout: 30          # 排队超时（秒）
```

### API 识别

使用 **Method + 路径** 格式识别 API：

```
POST /v1/chat/completions
GET /v1/models
```

对于带参数的路径，可配置路径模式：

```yaml
api_patterns:
  - pattern: "GET /users/{id}"      # 匹配 GET /users/123, GET /users/456
  - pattern: "POST /v1/chat/*"      # 匹配 POST /v1/chat/completions 等
```

### SSE 特殊处理

- **连接计数**：SSE 连接独立计数，不占用普通 HTTP 并发
- **消息计数**：SSE 消息与普通请求共享频率配额
- **空闲超时**：默认 60 秒无消息断开，可配置
- **消息限流**：达到频率上限时断开 SSE 连接

### SSE 错误处理

当 SSE 连接需要被 Pylon 主动断开时，先发送错误事件再关闭连接：

```
event: pylon_error
data: {"code": "rate_limit_exceeded", "message": "Request limit exceeded"}

[连接关闭]
```

**特点**：
- 使用 `event: pylon_error` 区分于 downstream 的普通消息
- 客户端可监听 `pylon_error` 事件单独处理

**错误码**：

| code | 说明 |
|------|------|
| `rate_limit_exceeded` | 请求频率超限 |
| `idle_timeout` | 空闲超时断开 |
| `downstream_error` | downstream 连接异常 |

### 配置示例

```yaml
rate_limit:
  global:
    max_concurrent: 50              # 普通 HTTP 并发上限
    max_requests_per_minute: 500    # 普通请求 + SSE 消息，每分钟
    max_sse_connections: 20         # SSE 并发连接上限

  default_user:                     # 未单独配置的用户使用此默认值
    max_concurrent: 4
    max_requests_per_minute: 60
    max_sse_connections: 2

  apis:                             # 按 API 限流（可选）
    "POST /v1/chat/completions":
      max_requests_per_minute: 100  # 该 API 全局最多 100/分钟
    "POST /v1/images/generate":
      max_requests_per_minute: 20   # 生成类 API 限制更严格

queue:
  max_size: 100                     # 队列上限
  timeout: 30                       # 排队超时（秒）

sse:
  idle_timeout: 60                  # 空闲超时（秒）
```

### 限流实现

使用内存存储计数器：
- **并发数**：原子计数器，请求开始 +1，结束 -1
- **请求频率**：滑动窗口计数器，按分钟统计

---

## API Key 认证

### 传递方式

```
Authorization: Bearer <api_key>
```

### 验证流程

1. 从 `Authorization` Header 提取 API Key
2. 计算 Key 的 SHA-256 哈希
3. 查询数据库匹配 `key_hash`
4. 验证：
   - Key 存在
   - 未过期（`expires_at` 为空或大于当前时间）
   - 未吊销（`revoked_at` 为空）

### API Key 格式

```
sk-<random_32_chars>

示例：sk-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
```

---

## 管理界面认证

### 认证方式

配置文件中存储密码的 bcrypt 哈希：

```yaml
admin:
  password_hash: "$2b$12$xxxxx..."  # bcrypt 哈希
```

### 生成密码哈希

```bash
python -m pylon hash-password
> Enter password: ****
> $2b$12$xxxxx...
```

### 登录流程

```
POST /login
Body: {"password": "xxx"}
     |
     v
bcrypt 验证 ---> 失败 ---> 401
     |
   成功
     |
     v
返回 JWT Token（有效期 24 小时）
     |
     v
后续请求带 Authorization: Bearer <jwt_token>
```

### 未来扩展

可扩展为独立账号体系，支持：
- 多管理员
- 在线修改密码
- 登录日志

---

## 管理界面功能

1. **API Key 管理**
   - 创建 API Key（设置描述、过期时间）
   - 查看 API Key 列表（ID、描述、状态、创建时间、过期时间）
   - 吊销 API Key
   - 刷新 API Key（生成新 Key，旧 Key 失效）
   - 配置单个 API Key 的限流规则

2. **实时监控**
   - 当前并发数（全局/各用户）
   - 当前 SSE 连接数
   - 请求频率趋势图
   - 各 API 调用频率

3. **统计报告**
   - 总体统计：请求总量、成功率、平均响应时间
   - 分用户统计：各 API Key 的使用情况
   - 分 API 统计：各 API 的调用次数、耗时、成功率
   - 时间范围筛选
   - 导出：JSON / CSV / HTML

4. **系统配置**
   - 全局限流配置
   - 默认用户限流配置
   - API 限流配置
   - 数据保留时长

### 技术实现

- **前端**：Vue 3 + Element Plus + Vite
- **API**：FastAPI 提供 RESTful 接口
- **实时数据**：WebSocket 或轮询

---

## 统计与报告

### 统计指标

| 指标 | 维度 | 说明 |
|------|------|------|
| 请求总量 | 全局 / 用户 / API | 普通请求 + SSE 消息总数 |
| 成功率 | 全局 / 用户 / API | 2xx 响应占比 |
| 平均响应时间 | 全局 / 用户 / API | 毫秒 |
| SSE 连接数 | 全局 / 用户 | SSE 连接建立次数 |
| SSE 消息总量 | 全局 / 用户 | SSE 消息条数 |
| 被限流次数 | 全局 / 用户 / API | 429 响应次数 |

### 数据保留

- 默认保留 1 个月
- 可配置保留时长
- 定时任务清理过期数据

### 导出格式

- **JSON**：结构化数据，便于程序处理
- **CSV**：便于 Excel 分析
- **HTML**：可视化报告，便于分享

---

## 配置文件

### 完整配置示例

```yaml
# config.yaml

server:
  proxy_port: 8000
  admin_port: 8001
  host: "0.0.0.0"

downstream:
  base_url: "https://api.example.com"
  timeout: 30

database:
  # SQLite
  type: "sqlite"
  path: "./data/pylon.db"

  # PostgreSQL (alternative)
  # type: "postgresql"
  # host: "localhost"
  # port: 5432
  # database: "pylon"
  # username: "pylon"
  # password: "secret"

admin:
  password_hash: "$2b$12$xxxxx..."  # bcrypt 哈希，用 pylon hash-password 生成
  jwt_secret: "your-jwt-secret"     # JWT 签名密钥
  jwt_expire_hours: 24              # JWT 有效期

rate_limit:
  global:
    max_concurrent: 50
    max_requests_per_minute: 500
    max_sse_connections: 20

  default_user:
    max_concurrent: 4
    max_requests_per_minute: 60
    max_sse_connections: 2

  apis:
    "POST /v1/chat/completions":
      max_requests_per_minute: 100
    "POST /v1/images/generate":
      max_requests_per_minute: 20

queue:
  max_size: 100
  timeout: 30

sse:
  idle_timeout: 60

data_retention:
  days: 30
  cleanup_interval_hours: 24

logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

---

## 项目结构

```
pylon/
├── docs/
│   └── design.md
├── pylon/
│   ├── __init__.py
│   ├── main.py                 # 应用入口（启动双端口服务）
│   ├── config.py               # 配置加载
│   ├── models/
│   │   ├── __init__.py
│   │   ├── api_key.py          # API Key 模型
│   │   └── request_log.py      # 请求日志模型
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth.py             # 认证服务
│   │   ├── proxy.py            # 代理服务
│   │   ├── rate_limiter.py     # 限流服务
│   │   └── stats.py            # 统计服务
│   ├── api/
│   │   ├── __init__.py
│   │   ├── proxy.py            # 代理路由（端口 8000）
│   │   └── admin.py            # 管理 API（端口 8001）
│   └── utils/
│       ├── __init__.py
│       └── crypto.py           # 加密工具
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── ApiKeys.vue     # API Key 管理页
│   │   │   ├── Monitor.vue     # 实时监控页
│   │   │   ├── Stats.vue       # 统计报告页
│   │   │   └── Settings.vue    # 系统配置页
│   │   ├── components/
│   │   ├── api/
│   │   └── App.vue
│   ├── package.json
│   └── vite.config.js
├── tests/
│   ├── unit/                   # 单元测试
│   ├── e2e/                    # 端到端测试
│   └── mock_server/            # Mock Downstream Server
│       └── app.py
├── config.yaml
├── requirements.txt
└── README.md
```

## 测试策略

### 单元测试

位于 `tests/unit/`，测试各模块独立功能：
- 认证服务：API Key 验证逻辑
- 限流服务：计数器、滑动窗口算法
- 加密工具：哈希生成与验证

### 端到端测试

位于 `tests/e2e/`，测试完整请求链路。

#### Mock Downstream Server

位于 `tests/mock_server/app.py`，模拟南向 API：

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
import asyncio

app = FastAPI()

@app.get("/api/hello")
def hello():
    return {"message": "hello"}

@app.post("/api/echo")
def echo(data: dict):
    return data

@app.get("/api/slow")
async def slow():
    await asyncio.sleep(2)
    return {"message": "slow response"}

@app.get("/api/error")
def error():
    raise HTTPException(status_code=500, detail="Internal error")

@app.get("/api/stream")
async def stream():
    async def generate():
        for i in range(5):
            yield f"data: message {i}\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(generate(), media_type="text/event-stream")
```

#### 测试 Fixture

```python
# tests/conftest.py
import pytest
from multiprocessing import Process

@pytest.fixture(scope="session")
def mock_downstream():
    process = Process(target=run_mock_server, args=(9999,))
    process.start()
    yield "http://localhost:9999"
    process.terminate()

@pytest.fixture(scope="session")
def pylon_proxy(mock_downstream):
    # 启动 Pylon，配置 downstream 指向 mock server
    process = Process(target=run_pylon, args=(8000, 8001, mock_downstream))
    process.start()
    yield {"proxy": "http://localhost:8000", "admin": "http://localhost:8001"}
    process.terminate()
```

#### 测试用例

- 无 API Key 请求 → 401
- 无效 API Key → 401
- 过期 API Key → 401
- 有效请求透传 → 200 + 正确响应
- 并发超限 → 进入队列等待
- 频率超限 → 429
- 队列超时 → 504
- 高优先级抢占低优先级 → 低优先级收到 503
- SSE 连接与消息
- SSE 空闲超时断开
- SSE 频率超限断开（收到 pylon_error 事件）

---

## 未来扩展方向

### Redis 支持

当前使用内存存储限流计数器，单机部署。未来可引入 Redis 支持多实例部署：

```yaml
rate_limit:
  storage:
    type: "redis"  # 或 "memory"
    redis:
      host: "localhost"
      port: 6379
      db: 0
```

**实现要点**：
- 限流计数器迁移到 Redis
- 使用 Redis 原子操作保证并发安全
- 利用 Redis TTL 自动清理过期计数

### 更多限流维度

- 每日/每月配额
- 按 API 路径限流
- 按 IP 限流
- 令牌桶/漏桶算法

### 更多认证方式

- OAuth 2.0
- JWT
- IP 白名单

---

## 开发计划

### 阶段一：核心功能

1. 项目初始化、配置加载
2. 数据库模型（API Key、请求日志）
3. API Key 认证
4. 基础代理功能（普通 HTTP）
5. 限流服务

### 阶段二：SSE 支持

6. SSE 代理
7. SSE 限流与超时

### 阶段三：管理界面

8. 管理 API
9. 前端：API Key 管理
10. 前端：实时监控
11. 前端：统计报告

### 阶段四：完善

12. 数据导出
13. 定时清理任务
14. 文档与测试
