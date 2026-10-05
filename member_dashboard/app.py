"""App factory with synthetic-safe startup and no production imports."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from .contracts import HealthResponse
from .errors import ErrorResponse
from .settings import Settings
from .store import WebStore
from .auth import AuthService
from .routes.auth import router as auth_router, AnonymousCsrf
from .routes.research import router as research_router
from .jobs import JobService
from .providers import ProviderRegistry
from .source_policy import SourcePolicy
from .assets import router as assets_router
from .routes.feed import router as feed_router
from .publication import FeedService
from .market_reader import MarketReader
from .history import HistoryService
from .routes.history import router as history_router
from .admin import AdminService
from .routes.admin import router as admin_router
from .assistant import AssistantService
from .routes.assistant import router as assistant_router


def create_app(settings: Settings) -> FastAPI:
    settings.validate_paths()
    store = WebStore(settings.web_path)

    @asynccontextmanager
    async def lifespan(app):
        settings.validate_paths()
        store.migrate()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.store = store
    app.state.clock = settings.clock
    app.state.providers = settings.provider_registry
    app.state.auth = AuthService(store)
    app.state.anonymous_csrf = AnonymousCsrf()
    app.state.source_policy = SourcePolicy(store)
    app.state.feed = (FeedService(store,app.state.auth,app.state.source_policy,
        signing_key=settings.feed_signing_key,clock=settings.clock,
        reader=MarketReader(settings.market_path,clock=settings.clock)) if settings.feed_signing_key else None)
    app.state.research = JobService(store, app.state.auth, app.state.source_policy,
        settings.provider_registry if isinstance(settings.provider_registry, ProviderRegistry) else ProviderRegistry())
    app.state.history = HistoryService(app.state.research, signing_key=settings.feed_signing_key, clock=settings.clock)
    app.state.assistant = AssistantService(app.state.history,transport=settings.assistant_transport,clock=settings.clock)
    app.state.admin = AdminService(store,app.state.auth,clock=settings.clock)
    app.include_router(admin_router)
    app.include_router(auth_router)
    app.include_router(research_router)
    app.include_router(assets_router)
    app.include_router(feed_router)
    app.include_router(history_router)
    app.include_router(assistant_router)

    def safe_error(status, code):
        return JSONResponse(status_code=status,
                            content=ErrorResponse(error=code, message="Request unavailable.").model_dump(),
                            headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return safe_error(422, "invalid_request")

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        code = {400: "invalid_request", 401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(error.status_code, "unavailable")
        return safe_error(error.status_code, code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        return safe_error(503, "unavailable")

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/healthz", response_model=HealthResponse)
    def health():
        return HealthResponse(status="ok")

    return app
