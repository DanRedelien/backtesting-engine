"""FastAPI entrypoint for the V2 terminal UI."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backtest_engine.bootstrap.composition_root import (
    ApplicationContainer,
    build_http_container,
)
from backtest_engine.config.settings import PlatformSettings
from backtest_engine.core.errors import BacktestEngineError
from backtest_engine.interfaces.terminal_ui.read_recommendation import (
    RecommendationRequest,
    read_recommendation,
)
from backtest_engine.interfaces.terminal_ui.read_confirmed_folds import (
    ConfirmedFoldsRequest,
    read_confirmed_folds,
)
from backtest_engine.interfaces.terminal_ui.read_latest_recommendation import (
    LatestRecommendationRequest,
    read_latest_recommendation,
)
from backtest_engine.interfaces.terminal_ui.read_study_champion import (
    StudyChampionRequest,
    read_study_champion,
)
from backtest_engine.interfaces.terminal_ui.read_study_summary import (
    StudySummaryRequest,
    read_study_summary,
)
from backtest_engine.interfaces.terminal_ui.query_service import TerminalUiQueryService


_UI_DIR = Path(__file__).parent
_TEMPLATES_DIR = _UI_DIR / "templates"
_STATIC_DIR = _UI_DIR / "static"


def _build_static_asset_version() -> str:
    """Build a cache-busting token from current terminal UI static assets."""

    static_files = sorted(path for path in _STATIC_DIR.rglob("*") if path.is_file())
    if not static_files:
        return "1"

    fingerprint = hashlib.sha1()
    for path in static_files:
        fingerprint.update(path.relative_to(_STATIC_DIR).as_posix().encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(path.read_bytes())
        fingerprint.update(b"\0")
    return fingerprint.hexdigest()[:16]


def create_terminal_ui_app(
    *,
    container: ApplicationContainer | None = None,
    settings: PlatformSettings | None = None,
    results_root: Path | None = None,
) -> FastAPI:
    """Create the V2 terminal UI over saved bundles and rerun planning."""

    resolved_container = container or build_http_container(settings=settings)
    query_service = TerminalUiQueryService(
        container=resolved_container,
        results_root=results_root or resolved_container.settings.runtime.results_root,
    )
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    static_asset_version = _build_static_asset_version()

    app = FastAPI(
        title="Backtesting Engine V2 Terminal UI",
        docs_url=None,
        redoc_url=None,
    )
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    def _render_dashboard(
        request: Request,
        *,
        selected_bundle_id: str | None = None,
        scenario_name: str = "",
        status_code: int = 200,
    ) -> HTMLResponse:
        page = query_service.build_dashboard_page(
            selected_bundle_id=selected_bundle_id,
            scenario_name=scenario_name,
            requested_by="terminal_ui_web",
        )
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "request": request,
                "page_title": "Backtesting Engine V2 Terminal UI",
                "static_asset_version": static_asset_version,
                "page": page,
            },
            status_code=status_code,
        )

    @app.get("/health")
    def health() -> JSONResponse:
        """Return a lightweight readiness payload for local launches."""

        return JSONResponse(
            content={"status": "ok", "results_root": query_service.results_root.as_posix()},
            headers={"X-Backtest-Engine-V2": "terminal-ui"},
        )

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        """Render the bundle dashboard against the V2 results root."""

        return _render_dashboard(request)

    @app.get("/bundles/{bundle_id}", response_class=HTMLResponse)
    def bundle_detail(
        request: Request,
        bundle_id: str,
        scenario_name: str = "",
    ) -> HTMLResponse:
        """Render one selected bundle and optional scenario plan preview."""

        return _render_dashboard(
            request,
            selected_bundle_id=bundle_id,
            scenario_name=scenario_name,
            status_code=200,
        )

    @app.get("/api/bundles")
    def bundle_index() -> JSONResponse:
        """Return the discovered V2 bundle catalog as JSON."""

        catalog = query_service.load_bundle_catalog()
        return JSONResponse(catalog.model_dump(mode="json"))

    @app.get("/api/bundles/{bundle_id}")
    def bundle_detail_json(bundle_id: str) -> JSONResponse:
        """Return one V2 bundle view as JSON."""

        try:
            detail = query_service.load_bundle_detail(bundle_id)
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=404,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(detail.model_dump(mode="json"))

    @app.get("/api/bundles/{bundle_id}/scenario-plan")
    def scenario_plan(bundle_id: str, scenario_name: str) -> JSONResponse:
        """Return one canonical scenario rerun plan for a saved bundle."""

        try:
            plan = query_service.build_scenario_plan(
                bundle_id=bundle_id,
                scenario_name=scenario_name,
                requested_by="terminal_ui_api",
            )
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(plan.model_dump(mode="json"))

    @app.get("/api/studies/summary")
    def study_summary(artifact_path: Path) -> JSONResponse:
        """Return one persisted study summary artifact as JSON."""

        try:
            summary = read_study_summary(
                StudySummaryRequest(artifact_path=artifact_path),
                query_service,
            )
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(summary.model_dump(mode="json"))

    @app.get("/api/recommendations")
    def recommendation(artifact_path: Path) -> JSONResponse:
        """Return one persisted live allocation recommendation as JSON."""

        try:
            recommendation = read_recommendation(
                RecommendationRequest(artifact_path=artifact_path),
                query_service,
            )
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(recommendation.model_dump(mode="json"))

    @app.get("/api/studies/folds")
    def confirmed_folds(artifact_path: Path) -> JSONResponse:
        """Return one persisted confirmed-fold collection as JSON."""

        try:
            folds = read_confirmed_folds(
                ConfirmedFoldsRequest(artifact_path=artifact_path),
                query_service,
            )
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(folds.model_dump(mode="json"))

    @app.get("/api/studies/champion")
    def study_champion(artifact_path: Path) -> JSONResponse:
        """Return one persisted study champion artifact as JSON."""

        try:
            champion = read_study_champion(
                StudyChampionRequest(artifact_path=artifact_path),
                query_service,
            )
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(champion.model_dump(mode="json"))

    @app.get("/api/recommendations/latest")
    def latest_recommendation(results_root: Path | None = None) -> JSONResponse:
        """Return the explicit latest recommendation surface as JSON."""

        try:
            recommendation = read_latest_recommendation(
                LatestRecommendationRequest(results_root=results_root or query_service.results_root),
                query_service,
            )
        except BacktestEngineError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": exc.message, "context": exc.context},
            )
        return JSONResponse(recommendation.model_dump(mode="json"))

    return app


app = create_terminal_ui_app()


__all__ = ["app", "create_terminal_ui_app"]
