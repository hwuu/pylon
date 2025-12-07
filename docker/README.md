# Docker 部署指南

## 快速开始

### 使用 Docker Compose

```bash
cd docker

# 构建并启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f

# 停止服务
docker compose down
```

服务启动后：
- 前端界面：http://localhost:5173
- 代理端口：http://localhost:8000
- 管理端口：http://localhost:8001
- Mock 服务：http://localhost:9999

默认管理员密码：`admin`

### 单独使用 Docker

#### 构建镜像

```bash
# 在项目根目录执行
docker build -f docker/Dockerfile -t pylon .
```

#### 启动代理服务

```bash
docker run -d \
  -v $(pwd)/data:/data \
  -v $(pwd)/config.yaml:/config/config.yaml:ro \
  -p 8000:8000 \
  -p 8001:8001 \
  --name pylon-proxy \
  pylon serve -c /config/config.yaml
```

#### 启动前端

```bash
docker run -d \
  -e API_BASE_URL=http://localhost:8001 \
  -p 5173:5173 \
  --name pylon-frontend \
  pylon frontend
```

#### 启动 Mock Server

```bash
docker run -d \
  -p 9999:9999 \
  --name pylon-mock \
  pylon mock
```

#### 生成密码哈希

```bash
docker run --rm -it pylon hash-password
```

## 命令说明

| 命令 | 说明 |
|------|------|
| `serve -c <config>` | 启动代理和管理服务 |
| `frontend` | 启动前端 Nginx 服务 |
| `mock` | 启动 Mock Server |
| `hash-password` | 交互式生成密码哈希 |

## 配置

### 代理服务配置

创建 `config.yaml`：

```yaml
server:
  proxy_port: 8000
  admin_port: 8001
  host: "0.0.0.0"

database:
  # 使用挂载的 volume
  url: "sqlite+aiosqlite:////data/pylon.db"

admin:
  password_hash: "$2b$12$..."  # 使用 hash-password 生成
  jwt_secret: "your-secret-key"
  jwt_expire_hours: 24

logging:
  level: "INFO"
```

### 前端配置

通过环境变量 `API_BASE_URL` 指定后端管理服务地址：

```bash
docker run -e API_BASE_URL=http://192.168.1.100:8001 -p 5173:5173 pylon frontend
```

### 数据持久化

SQLite 数据库存储在 `/data` 目录，需要挂载 volume：

```bash
docker run -v /host/path/data:/data ... pylon serve
```

## 网络配置

### 外部访问

如果需要从其他机器访问：

1. 前端的 `API_BASE_URL` 需要设置为后端服务的**外部可访问地址**
2. 后端服务需要监听 `0.0.0.0`（默认配置已设置）

```bash
# 假设服务器 IP 为 192.168.1.100
docker run -e API_BASE_URL=http://192.168.1.100:8001 -p 5173:5173 pylon frontend
```

### Docker Compose 网络

默认情况下，docker-compose 中的服务可以通过服务名互相访问：

```yaml
environment:
  - API_BASE_URL=http://proxy:8001  # 容器内部访问
```

但前端运行在用户浏览器中，所以 `API_BASE_URL` 必须是**用户浏览器能访问到的地址**。

## 故障排查

### 查看日志

```bash
# 所有服务
docker compose logs -f

# 单个服务
docker compose logs -f proxy
docker compose logs -f frontend
```

### 进入容器调试

```bash
docker compose exec proxy bash
docker compose exec frontend bash
```

### 常见问题

**Q: 前端无法连接后端**

检查 `API_BASE_URL` 是否正确设置为浏览器可访问的地址。

**Q: 数据库权限错误**

确保挂载目录有写权限：
```bash
chmod 777 /host/path/data
```

**Q: 容器启动失败**

查看详细日志：
```bash
docker logs pylon-proxy
```
