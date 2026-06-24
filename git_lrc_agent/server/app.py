"""FastAPI dashboard server for git-lrc-agent.

Serves the review dashboard as a single-page application.  Designed to
start on a random available port, auto-open the browser, and shut down
after the user makes a commit/skip decision.

Usage::

    from git_lrc_agent.server.app import start_dashboard
    start_dashboard(review)  # blocks until user decides
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from git_lrc_agent.output.structured_output import StructuredReview


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(review: StructuredReview) -> FastAPI:
    """Create a FastAPI app configured to serve a specific review."""
    app = FastAPI(
        title="git-lrc Review Dashboard",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    # Store the review in app state.
    app.state.review = review
    app.state.decision = None  # Will be set by POST /api/decision
    app.state.shutdown_event = threading.Event()

    # Mount static files.
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the main dashboard page."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return HTMLResponse(index_path.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>git-lrc Dashboard</h1><p>Static files not found.</p>")

    @app.get("/api/review")
    async def get_review():
        """Return the full structured review as JSON."""
        return JSONResponse(json.loads(app.state.review.to_json()))

    @app.get("/api/files")
    async def get_files():
        """Return the list of reviewed files with summary stats."""
        files = []
        for f in app.state.review.files:
            file_issues = [
                i for i in app.state.review.issues
                if i.file == f.filename
            ]
            files.append({
                "filename": f.filename,
                "lines_added": f.lines_added,
                "lines_removed": f.lines_removed,
                "issue_count": len(file_issues),
                "max_severity": max(
                    (i.severity.value for i in file_issues),
                    default=None,
                    key=lambda s: ["info", "low", "medium", "high", "critical"].index(s) if s else -1,
                ),
            })
        return JSONResponse(files)

    @app.get("/api/issues")
    async def get_issues(
        pillar: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        file: Optional[str] = None,
    ):
        """Return filtered issues."""
        issues = app.state.review.issues
        if pillar:
            issues = [i for i in issues if i.pillar == pillar]
        if category:
            issues = [i for i in issues if i.category == category]
        if severity:
            issues = [i for i in issues if i.severity.value == severity]
        if file:
            issues = [i for i in issues if i.file == file]
        return JSONResponse([json.loads(i.model_dump_json()) for i in issues])

    @app.get("/api/summary")
    async def get_summary():
        """Return the review summary."""
        return JSONResponse(json.loads(app.state.review.summary.model_dump_json()))

    @app.post("/api/decision")
    async def post_decision(body: dict):
        """Record the user's commit/skip decision."""
        decision = body.get("decision", "skip")
        if decision not in ("commit", "skip", "commit_push"):
            raise HTTPException(400, "Invalid decision. Must be 'commit', 'skip', or 'commit_push'.")
        app.state.decision = decision
        app.state.shutdown_event.set()
        return JSONResponse({"status": "ok", "decision": decision})

    @app.get("/api/taxonomy")
    async def get_taxonomy():
        """Return the issue taxonomy for the filter panel."""
        from git_lrc_agent.taxonomy.taxonomy import ALL_PILLARS
        taxonomy = {}
        for pillar in ALL_PILLARS:
            taxonomy[pillar.name] = {}
            for cat in pillar.categories:
                taxonomy[pillar.name][cat.name] = [p.name for p in cat.patterns]
        return JSONResponse(taxonomy)

    return app


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def _find_free_port() -> int:
    """Find an available port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_dashboard(
    review: StructuredReview,
    *,
    port: int | None = None,
    open_browser: bool = True,
    block: bool = True,
) -> Optional[str]:
    """Start the dashboard server.

    Parameters
    ----------
    review
        The structured review to display.
    port
        Port number.  Auto-selected if None.
    open_browser
        Whether to open the browser automatically.
    block
        Whether to block until the user makes a decision.

    Returns
    -------
    str | None
        The user's decision ("commit", "skip", "commit_push") if blocking,
        or None if non-blocking.
    """
    import uvicorn

    if port is None:
        port = _find_free_port()

    app = create_app(review)
    url = f"http://localhost:{port}"

    print(f"🌐 Dashboard: {url}")

    if open_browser:
        # Open browser after a small delay to let the server start.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    if block:
        # Run in a thread so we can wait for the shutdown event.
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # Wait for user decision.
        app.state.shutdown_event.wait(timeout=3600)  # 1 hour timeout
        decision = app.state.decision or "skip"

        # Shut down the server.
        server.should_exit = True
        thread.join(timeout=5)

        return decision
    else:
        # Non-blocking: just start the server.
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, daemon=True).start()
        return None
