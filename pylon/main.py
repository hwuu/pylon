"""
Pylon main application entry point.
"""

import asyncio
import logging
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from pylon.config import load_config, Config
from pylon.models import init_db, create_async_db_engine, create_async_session_factory
from pylon.services.proxy import ProxyService
from pylon.services.rate_limiter import RateLimiter
from pylon.services.admin_auth import AdminAuthService
from pylon.services.cleanup import CleanupService
from pylon.api import proxy as proxy_api
from pylon.api import admin as admin_api


logger = logging.getLogger(__name__)


def create_proxy_app(config: Config, engine, session_factory, rate_limiter) -> FastAPI:
    """Create the proxy FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        logger.info("Starting Pylon proxy server...")

        # Initialize services
        proxy_service = ProxyService(config.downstream)

        # Set dependencies for routes
        proxy_api.set_dependencies(
            proxy_service, rate_limiter, session_factory, config.sse.idle_timeout
        )

        app.state.proxy_service = proxy_service
        app.state.rate_limiter = rate_limiter
        app.state.session_factory = session_factory
        app.state.engine = engine

        logger.info(f"Proxy server ready, forwarding to {config.downstream.base_url}")

        yield

        # Shutdown
        logger.info("Shutting down Pylon proxy server...")
        await proxy_service.close()
        await engine.dispose()

    app = FastAPI(
        title="Pylon Proxy",
        description="HTTP API Proxy with authentication and rate limiting",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include proxy routes
    app.include_router(proxy_api.router)

    return app


def create_admin_app(config: Config, session_factory, rate_limiter) -> FastAPI:
    """Create the admin FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting Pylon admin server...")

        # Initialize admin auth service
        admin_auth_service = AdminAuthService(config.admin)

        # Set dependencies for admin routes (including config for Settings page)
        admin_api.set_dependencies(admin_auth_service, session_factory, rate_limiter, config)

        app.state.admin_auth_service = admin_auth_service

        yield
        logger.info("Shutting down Pylon admin server...")

    app = FastAPI(
        title="Pylon Admin",
        description="Pylon administration API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include admin routes
    app.include_router(admin_api.router)

    return app


async def run_servers(config: Config):
    """Run both proxy and admin servers."""
    # Initialize shared resources first
    engine = create_async_db_engine(config.database)
    async with engine.begin() as conn:
        from pylon.models.database import Base
        await conn.run_sync(Base.metadata.create_all)

    session_factory = create_async_session_factory(engine)
    rate_limiter = RateLimiter(config.rate_limit, config.queue)

    # Create user config loader callback for rate limiter
    async def load_user_rate_limit_config(user_id: str):
        """Load user's rate_limit_config from database."""
        from sqlalchemy import select
        from pylon.models.api_key import ApiKey

        async with session_factory() as session:
            result = await session.execute(
                select(ApiKey.rate_limit_config).where(ApiKey.id == user_id)
            )
            row = result.first()
            if row and row[0]:
                return row[0]
            return None

    rate_limiter.set_user_config_loader(load_user_rate_limit_config)

    # Initialize cleanup service
    cleanup_service = CleanupService(session_factory, config.data_retention)
    cleanup_service.start()

    # Create apps with shared resources
    proxy_app = create_proxy_app(config, engine, session_factory, rate_limiter)
    admin_app = create_admin_app(config, session_factory, rate_limiter)

    proxy_config = uvicorn.Config(
        proxy_app,
        host=config.server.host,
        port=config.server.proxy_port,
        log_level=config.logging.level.lower(),
    )
    admin_config = uvicorn.Config(
        admin_app,
        host=config.server.host,
        port=config.server.admin_port,
        log_level=config.logging.level.lower(),
    )

    proxy_server = uvicorn.Server(proxy_config)
    admin_server = uvicorn.Server(admin_config)

    logger.info(f"Proxy server: http://{config.server.host}:{config.server.proxy_port}")
    logger.info(f"Admin server: http://{config.server.host}:{config.server.admin_port}")

    try:
        await asyncio.gather(
            proxy_server.serve(),
            admin_server.serve(),
        )
    finally:
        await cleanup_service.stop()


def cmd_serve(args):
    """Run the proxy and admin servers."""
    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        print("Please create a config.yaml file or specify a different path with -c")
        return 1

    config = load_config(config_path)

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.logging.level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run servers
    try:
        asyncio.run(run_servers(config))
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")

    return 0


def cmd_hash_password(args):
    """Generate bcrypt hash for admin password."""
    import getpass
    from pylon.utils import hash_password

    try:
        password = getpass.getpass("Enter password: ")
        if not password:
            print("Error: Password cannot be empty")
            return 1

        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("Error: Passwords do not match")
            return 1

        hashed = hash_password(password)
        print(f"\nGenerated password hash:")
        print(hashed)
        print(f"\nAdd this to your config.yaml:")
        print(f'admin:')
        print(f'  password_hash: "{hashed}"')

    except KeyboardInterrupt:
        print("\nCancelled")
        return 1

    return 0


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Pylon HTTP API Proxy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve command (default)
    serve_parser = subparsers.add_parser("serve", help="Run the proxy and admin servers")
    serve_parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )

    # hash-password command
    subparsers.add_parser("hash-password", help="Generate bcrypt hash for admin password")

    args = parser.parse_args()

    # Default to serve if no command specified
    if args.command is None:
        # Re-parse with serve as default
        args.command = "serve"
        args.config = "config.yaml"

    if args.command == "serve":
        return cmd_serve(args)
    elif args.command == "hash-password":
        return cmd_hash_password(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    exit(main())
