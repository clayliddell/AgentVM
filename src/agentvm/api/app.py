"""FastAPI application factory.

Ref: REST-API-LLD §3.1
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Ref: REST-API-LLD §3.1
    """
    app = FastAPI(title="AgentVM")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
