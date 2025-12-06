"""
Pylon configuration loader.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class ServerConfig:
    proxy_port: int = 8000
    admin_port: int = 8001
    host: str = "0.0.0.0"


@dataclass
class DownstreamConfig:
    base_url: str = ""
    timeout: int = 30


@dataclass
class DatabaseConfig:
    type: str = "sqlite"
    path: str = "./data/pylon.db"
    # PostgreSQL options
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@dataclass
class AdminConfig:
    password_hash: str = ""
    jwt_secret: str = ""
    jwt_expire_hours: int = 24


@dataclass
class RateLimitRule:
    max_concurrent: Optional[int] = None
    max_requests_per_minute: Optional[int] = None
    max_sse_connections: Optional[int] = None


@dataclass
class ApiPattern:
    """API pattern with rate limit rule."""
    pattern: str  # e.g., "GET /users/{id}" or "POST /v1/chat/*"
    rule: RateLimitRule


@dataclass
class RateLimitConfig:
    global_limit: RateLimitRule = field(default_factory=lambda: RateLimitRule(
        max_concurrent=50,
        max_requests_per_minute=500,
        max_sse_connections=20
    ))
    default_user: RateLimitRule = field(default_factory=lambda: RateLimitRule(
        max_concurrent=4,
        max_requests_per_minute=60,
        max_sse_connections=2
    ))
    apis: dict[str, RateLimitRule] = field(default_factory=dict)
    api_patterns: list[ApiPattern] = field(default_factory=list)


@dataclass
class QueueConfig:
    max_size: int = 100
    timeout: int = 30


@dataclass
class SSEConfig:
    idle_timeout: int = 60


@dataclass
class DataRetentionConfig:
    days: int = 30
    cleanup_interval_hours: int = 24


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    downstream: DownstreamConfig = field(default_factory=DownstreamConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    sse: SSEConfig = field(default_factory=SSEConfig)
    data_retention: DataRetentionConfig = field(default_factory=DataRetentionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _parse_rate_limit_rule(data: dict) -> RateLimitRule:
    """Parse a rate limit rule from dict."""
    return RateLimitRule(
        max_concurrent=data.get("max_concurrent"),
        max_requests_per_minute=data.get("max_requests_per_minute"),
        max_sse_connections=data.get("max_sse_connections"),
    )


def load_config(config_path: str | Path) -> Config:
    """Load configuration from a YAML file."""
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    config = Config()

    # Server
    if "server" in data:
        server_data = data["server"]
        config.server = ServerConfig(
            proxy_port=server_data.get("proxy_port", 8000),
            admin_port=server_data.get("admin_port", 8001),
            host=server_data.get("host", "0.0.0.0"),
        )

    # Downstream
    if "downstream" in data:
        downstream_data = data["downstream"]
        config.downstream = DownstreamConfig(
            base_url=downstream_data.get("base_url", ""),
            timeout=downstream_data.get("timeout", 30),
        )

    # Database
    if "database" in data:
        db_data = data["database"]
        config.database = DatabaseConfig(
            type=db_data.get("type", "sqlite"),
            path=db_data.get("path", "./data/pylon.db"),
            host=db_data.get("host"),
            port=db_data.get("port"),
            database=db_data.get("database"),
            username=db_data.get("username"),
            password=db_data.get("password"),
        )

    # Admin
    if "admin" in data:
        admin_data = data["admin"]
        config.admin = AdminConfig(
            password_hash=admin_data.get("password_hash", ""),
            jwt_secret=admin_data.get("jwt_secret", ""),
            jwt_expire_hours=admin_data.get("jwt_expire_hours", 24),
        )

    # Rate limit
    if "rate_limit" in data:
        rl_data = data["rate_limit"]

        global_limit = config.rate_limit.global_limit
        if "global" in rl_data:
            global_limit = _parse_rate_limit_rule(rl_data["global"])

        default_user = config.rate_limit.default_user
        if "default_user" in rl_data:
            default_user = _parse_rate_limit_rule(rl_data["default_user"])

        apis = {}
        if "apis" in rl_data and rl_data["apis"]:
            for api_path, api_limit in rl_data["apis"].items():
                apis[api_path] = _parse_rate_limit_rule(api_limit)

        api_patterns = []
        if "api_patterns" in rl_data and rl_data["api_patterns"]:
            for pattern_data in rl_data["api_patterns"]:
                pattern = pattern_data.get("pattern", "")
                if pattern:
                    rule = _parse_rate_limit_rule(pattern_data)
                    api_patterns.append(ApiPattern(pattern=pattern, rule=rule))

        config.rate_limit = RateLimitConfig(
            global_limit=global_limit,
            default_user=default_user,
            apis=apis,
            api_patterns=api_patterns,
        )

    # Queue
    if "queue" in data:
        queue_data = data["queue"]
        config.queue = QueueConfig(
            max_size=queue_data.get("max_size", 100),
            timeout=queue_data.get("timeout", 30),
        )

    # SSE
    if "sse" in data:
        sse_data = data["sse"]
        config.sse = SSEConfig(
            idle_timeout=sse_data.get("idle_timeout", 60),
        )

    # Data retention
    if "data_retention" in data:
        dr_data = data["data_retention"]
        config.data_retention = DataRetentionConfig(
            days=dr_data.get("days", 30),
            cleanup_interval_hours=dr_data.get("cleanup_interval_hours", 24),
        )

    # Logging
    if "logging" in data:
        logging_data = data["logging"]
        config.logging = LoggingConfig(
            level=logging_data.get("level", "INFO"),
        )

    return config
