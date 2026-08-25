"""`ida-api` console script -- the container's api command.

One image, several commands (see .devops/components.yaml): this entry point is
what the `api` Deployment runs; `ida-runner` and `ida-mock-model` are the other
two, from the SAME image. Build once, run three ways.
"""

from __future__ import annotations

import uvicorn

from ida_core.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ida_api.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
