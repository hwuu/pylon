# Pylon 手动测试指南

本文档提供完整的手动端到端测试流程，帮助你快速体验 Pylon 的全部功能。

## 目录

- [1. 环境准备](#1-环境准备)
- [2. 启动 Mock Server](#2-启动-mock-server)
- [3. 配置 Pylon](#3-配置-pylon)
- [4. 启动 Pylon](#4-启动-pylon)
- [5. 管理员登录](#5-管理员登录)
- [6. 创建 API Key](#6-创建-api-key)
- [7. 代理请求测试](#7-代理请求测试)
- [8. 触发限流](#8-触发限流)
- [9. 查看监控数据](#9-查看监控数据)
- [10. 查看统计报告](#10-查看统计报告)
- [11. 导出统计数据](#11-导出统计数据)
- [12. 前端界面使用](#12-前端界面使用)

---

## 1. 环境准备

```bash
# 安装 Python 依赖
pip install -r requirements.txt

# 安装前端依赖（可选，用于启动前端界面）
cd frontend && npm install && cd ..
```

---

## 2. 启动 Mock Server

Mock Server 模拟下游 API，用于测试代理功能。

```bash
# 在终端 1 启动 Mock Server（端口 9999）
python -m tests.mock_server.app
```

验证 Mock Server 是否正常：

```bash
curl http://localhost:9999/api/hello
# 预期输出: {"message":"hello"}

curl http://localhost:9999/v1/models
# 预期输出: {"object":"list","data":[{"id":"gpt-4","object":"model"},{"id":"gpt-3.5-turbo","object":"model"}]}
```

---

## 3. 配置 Pylon

### 3.1 生成管理员密码哈希

```bash
python -c "from pylon.utils.crypto import hash_password; print(hash_password('admin123'))"
```

记录输出的哈希值（类似 `$2b$12$...`）。

### 3.2 创建配置文件

创建 `config.yaml`：

```yaml
server:
  proxy_port: 8000
  admin_port: 8001
  host: "127.0.0.1"

downstream:
  base_url: "http://localhost:9999"
  timeout: 30

database:
  type: "sqlite"
  path: "./data/pylon.db"

admin:
  password_hash: "$2b$12$你的密码哈希"  # 替换为上一步生成的哈希
  jwt_secret: "your-secret-key-change-in-production"
  jwt_expire_hours: 24

rate_limit:
  global:
    max_concurrent: 10
    max_requests_per_minute: 60
    max_sse_connections: 5
  default_user:
    max_concurrent: 2
    max_requests_per_minute: 10
    max_sse_connections: 1

queue:
  max_size: 20
  timeout: 10

sse:
  idle_timeout: 30

data_retention:
  days: 30
  cleanup_interval_hours: 24
```

---

## 4. 启动 Pylon

```bash
# 在终端 2 启动 Pylon
python -m pylon -c config.yaml
```

预期输出：
```
INFO - Proxy server: http://127.0.0.1:8000
INFO - Admin server: http://127.0.0.1:8001
INFO - Cleanup service started (retention: 30 days, interval: 24 hours)
```

验证服务健康：

```bash
# 代理端口健康检查
curl http://localhost:8000/health

# 管理端口健康检查
curl http://localhost:8001/health
```

---

## 5. 管理员登录

```bash
# 登录获取 JWT Token
curl -X POST http://localhost:8001/login \
  -H "Content-Type: application/json" \
  -d '{"password": "admin123"}'
```

预期输出：
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in_hours": 24
}
```

保存 token 用于后续请求：

```bash
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## 6. 创建 API Key

### 6.1 创建普通优先级 Key

```bash
curl -X POST http://localhost:8001/api-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"description": "Test User", "priority": "normal"}'
```

预期输出：
```json
{
  "id": "uuid-xxxx",
  "key": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "key_prefix": "sk-xxx",
  "description": "Test User",
  "priority": "normal",
  "created_at": "2024-01-01T00:00:00Z",
  "expires_at": null
}
```

**重要**：保存返回的 `key`，它只显示一次！

```bash
export API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### 6.2 创建高优先级 Key

```bash
curl -X POST http://localhost:8001/api-keys \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"description": "VIP User", "priority": "high", "expires_in_days": 30}'
```

### 6.3 查看所有 API Key

```bash
curl http://localhost:8001/api-keys \
  -H "Authorization: Bearer $TOKEN"
```

### 6.4 查看 API Key 统计

```bash
curl http://localhost:8001/api-keys/count \
  -H "Authorization: Bearer $TOKEN"
```

---

## 7. 代理请求测试

### 7.1 无认证请求（应被拒绝）

```bash
curl http://localhost:8000/api/hello
# 预期: 401 Unauthorized
```

### 7.2 使用有效 API Key

```bash
curl http://localhost:8000/api/hello \
  -H "Authorization: Bearer $API_KEY"
# 预期: {"message":"hello"}
```

### 7.3 POST 请求

```bash
curl -X POST http://localhost:8000/api/echo \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"test": "data", "number": 42}'
# 预期: {"test":"data","number":42}
```

### 7.4 OpenAI 风格请求

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'
```

### 7.5 SSE 流式请求

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}], "stream": true}'
```

---

## 8. 触发限流

根据配置 `default_user.max_requests_per_minute: 10`，快速发送请求触发限流。

### 8.1 快速发送多个请求

```bash
# 使用循环快速发送 15 个请求
for i in {1..15}; do
  echo "Request $i:"
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://localhost:8000/api/hello \
    -H "Authorization: Bearer $API_KEY"
done
```

预期：前 10 个请求返回 200，之后的请求返回 429。

### 8.2 查看限流响应

```bash
curl -i http://localhost:8000/api/hello \
  -H "Authorization: Bearer $API_KEY"
```

当被限流时，返回：
```
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{"detail":"Rate limit exceeded"}
```

### 8.3 测试并发限制

打开多个终端，同时发送慢请求：

```bash
# 终端 A
curl http://localhost:8000/api/slow -H "Authorization: Bearer $API_KEY"

# 终端 B（同时执行）
curl http://localhost:8000/api/slow -H "Authorization: Bearer $API_KEY"

# 终端 C（同时执行）- 会进入队列
curl http://localhost:8000/api/slow -H "Authorization: Bearer $API_KEY"
```

根据 `default_user.max_concurrent: 2`，第三个请求会进入队列等待。

---

## 9. 查看监控数据

```bash
curl http://localhost:8001/monitor \
  -H "Authorization: Bearer $TOKEN"
```

预期输出：
```json
{
  "global_concurrent": 2,
  "global_sse_connections": 0,
  "global_requests_this_minute": 15,
  "queue_size": 1
}
```

---

## 10. 查看统计报告

### 10.1 全局统计

```bash
curl http://localhost:8001/stats/summary \
  -H "Authorization: Bearer $TOKEN"
```

预期输出：
```json
{
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-08T00:00:00Z",
  "total_requests": 25,
  "total_sse_messages": 0,
  "total_count": 25,
  "success_rate": 60.0,
  "avg_response_time_ms": 150.5,
  "sse_connections": 0,
  "rate_limited_count": 10
}
```

### 10.2 按用户统计

```bash
curl http://localhost:8001/stats/users \
  -H "Authorization: Bearer $TOKEN"
```

### 10.3 按 API 统计

```bash
curl http://localhost:8001/stats/apis \
  -H "Authorization: Bearer $TOKEN"
```

### 10.4 指定时间范围

```bash
# 查询最近 24 小时
curl "http://localhost:8001/stats/summary?start_time=2024-01-07T00:00:00Z&end_time=2024-01-08T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN"
```

---

## 11. 导出统计数据

### 11.1 导出 JSON

```bash
curl "http://localhost:8001/stats/export?format=json" \
  -H "Authorization: Bearer $TOKEN" \
  -o stats.json
```

### 11.2 导出 CSV

```bash
curl "http://localhost:8001/stats/export?format=csv" \
  -H "Authorization: Bearer $TOKEN" \
  -o stats.csv
```

### 11.3 导出 HTML 报告

```bash
curl "http://localhost:8001/stats/export?format=html" \
  -H "Authorization: Bearer $TOKEN" \
  -o stats.html

# 在浏览器中打开
open stats.html  # macOS
start stats.html # Windows
```

---

## 12. 前端界面使用

### 12.1 启动前端开发服务器

```bash
cd frontend
npm run dev
```

访问 http://localhost:5173

### 12.2 登录

- 输入密码：`admin123`（或你配置的密码）
- 点击 Login

### 12.3 API Key 管理

- 点击侧边栏 "API Keys"
- 点击 "Create API Key" 创建新 Key
- 可以设置描述、优先级、过期时间
- 创建后会显示完整 Key（仅显示一次，请复制保存）
- 可以对 Key 进行刷新、吊销、删除操作

### 12.4 实时监控

- 点击侧边栏 "Monitor"
- 查看当前并发数、SSE 连接数、请求速率、队列长度
- 数据每 2 秒自动刷新

### 12.5 统计报告

- 点击侧边栏 "Stats"
- 选择时间范围（24小时/7天/30天/自定义）
- 查看汇总数据卡片
- 切换 "By User" / "By API" 标签查看详细统计
- 点击 "Export" 下拉菜单导出报告

---

## 附录：API 端点速查

### 代理端口 (8000)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查（无需认证） |
| * | /* | 代理所有请求到下游 API |

### 管理端口 (8001)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查 |
| POST | /login | 管理员登录 |
| GET | /api-keys | 列出 API Key |
| POST | /api-keys | 创建 API Key |
| GET | /api-keys/{id} | 获取单个 Key |
| PUT | /api-keys/{id} | 更新 Key |
| POST | /api-keys/{id}/revoke | 吊销 Key |
| POST | /api-keys/{id}/refresh | 刷新 Key |
| DELETE | /api-keys/{id} | 删除 Key |
| GET | /api-keys/count | Key 统计 |
| GET | /monitor | 实时监控数据 |
| GET | /stats/summary | 统计汇总 |
| GET | /stats/users | 按用户统计 |
| GET | /stats/apis | 按 API 统计 |
| GET | /stats/export | 导出报告 |
