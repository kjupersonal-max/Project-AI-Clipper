"""Run the API locally with safe auto-reload.

Uvicorn's default --reload watches the entire backend/ working tree, including
runtime data directories (uploads/, transcripts/, audio/, etc.). Pipeline and
upload writes under those paths can trigger reloads while requests are in flight,
leaving the worker stuck in "Waiting for connections to close" and causing new
uploads to hang at 0% with Pending OPTIONS/POST requests.
"""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["app"],
    )
