"""
Pylon configuration loader.

Configuration is split into two parts:
- Config: Static configuration from config.yaml (server, database, admin)
- Policy: Dynamic configuration from database (downstream, rate_limit, queue, sse, data_retention)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


# =============================================================================
# Static Config (from config.yaml)
# =============================================================================


@dataclass
class ServerConfig:
    proxy_port: int = 8000
    admin_port: int = 8001
    host: str = "0.0.0.0"


@dataclass
class DatabaseConfig:
    url: str = "sqlite+aiosqlite:///./data/pylon.db"


@dataclass
class AdminConfig:
    password_hash: str = ""
    jwt_secret: str = ""
    jwt_expire_hours: int = 24


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class Config:
    """Static configuration loaded from config.yaml."""
    server: ServerConfig = field(default_factory=ServerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(config_path: str | Path) -> Config:
    """Load static configuration from a YAML file."""
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

    # Database
    if "database" in data:
        db_data = data["database"]
        config.database = DatabaseConfig(
            url=db_data.get("url", "sqlite+aiosqlite:///./data/pylon.db"),
        )

    # Admin
    if "admin" in data:
        admin_data = data["admin"]
        config.admin = AdminConfig(
            password_hash=admin_data.get("password_hash", ""),
            jwt_secret=admin_data.get("jwt_secret", ""),
            jwt_expire_hours=admin_data.get("jwt_expire_hours", 24),
        )

    # Logging
    if "logging" in data:
        logging_data = data["logging"]
        config.logging = LoggingConfig(
            level=logging_data.get("level", "INFO"),
        )

    return config


# =============================================================================
# Policy Structures (from database)
# =============================================================================


@dataclass
class DownstreamConfig:
    base_url: str = ""
    timeout: int = 30


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
class PolicyConfig:
    """Dynamic configuration loaded from database."""
    downstream: DownstreamConfig = field(default_factory=DownstreamConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    sse: SSEConfig = field(default_factory=SSEConfig)
    data_retention: DataRetentionConfig = field(default_factory=DataRetentionConfig)


def _parse_rate_limit_rule(data: dict) -> RateLimitRule:
    """Parse a rate limit rule from dict."""
    return RateLimitRule(
        max_concurrent=data.get("max_concurrent"),
        max_requests_per_minute=data.get("max_requests_per_minute"),
        max_sse_connections=data.get("max_sse_connections"),
    )


def policy_from_dict(policy_dict: dict[str, Any]) -> PolicyConfig:
    """Build PolicyConfig from a flat key-value dict (from database)."""
    policy = PolicyConfig()

    # Downstream
    if "downstream.base_url" in policy_dict:
        policy.downstream.base_url = policy_dict["downstream.base_url"]
    if "downstream.timeout" in policy_dict:
        policy.downstream.timeout = policy_dict["downstream.timeout"]

    # Rate limit - global
    if "rate_limit.global" in policy_dict:
        data = policy_dict["rate_limit.global"]
        policy.rate_limit.global_limit = _parse_rate_limit_rule(data)

    # Rate limit - default_user
    if "rate_limit.default_user" in policy_dict:
        data = policy_dict["rate_limit.default_user"]
        policy.rate_limit.default_user = _parse_rate_limit_rule(data)

    # Rate limit - apis
    if "rate_limit.apis" in policy_dict:
        apis_data = policy_dict["rate_limit.apis"]
        for api_path, api_limit in apis_data.items():
            policy.rate_limit.apis[api_path] = _parse_rate_limit_rule(api_limit)

    # Rate limit - api_patterns
    if "rate_limit.api_patterns" in policy_dict:
        patterns_data = policy_dict["rate_limit.api_patterns"]
        for pattern_data in patterns_data:
            pattern = pattern_data.get("pattern", "")
            if pattern:
                rule_data = pattern_data.get("rule", {})
                rule = _parse_rate_limit_rule(rule_data)
                policy.rate_limit.api_patterns.append(ApiPattern(pattern=pattern, rule=rule))

    # Queue
    if "queue.max_size" in policy_dict:
        policy.queue.max_size = policy_dict["queue.max_size"]
    if "queue.timeout" in policy_dict:
        policy.queue.timeout = policy_dict["queue.timeout"]

    # SSE
    if "sse.idle_timeout" in policy_dict:
        policy.sse.idle_timeout = policy_dict["sse.idle_timeout"]

    # Data retention
    if "data_retention.days" in policy_dict:
        policy.data_retention.days = policy_dict["data_retention.days"]
    if "data_retention.cleanup_interval_hours" in policy_dict:
        policy.data_retention.cleanup_interval_hours = policy_dict["data_retention.cleanup_interval_hours"]

    return policy
