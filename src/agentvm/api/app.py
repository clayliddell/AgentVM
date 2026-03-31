"""FastAPI application factory.

Ref: REST-API-LLD §3.1
"""

from __future__ import annotations

from fastapi import FastAPI  # type: ignore[import-not-found]


def create_app() -> FastAPI:
    """Build and configure the FastAPI application.

    Ref: REST-API-LLD §3.1
    """
    app = FastAPI(title="AgentVM")

    @app.get("/health")  # type: ignore[untyped-decorator]
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
