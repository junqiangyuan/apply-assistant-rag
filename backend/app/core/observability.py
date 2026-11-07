import os

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def configure_observability() -> None:
    if settings.observability_enabled:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        logger.info(
            "LangSmith tracing enabled: project=%s endpoint=%s",
            settings.langsmith_project,
            settings.langsmith_endpoint,
        )
    else:
        os.environ["LANGSMITH_TRACING"] = "false"
        logger.info("LangSmith tracing disabled (no Langsmith_api key or switch off)")


def get_current_trace_id() -> str | None:
    if not settings.observability_enabled:
        return None
    try:
        from langsmith.run_helpers import get_current_run_tree

        run = get_current_run_tree()
        if run is None:
            return None
        return str(run.trace_id)
    except Exception:
        logger.warning("get current trace id 异常，返回None", exc_info=True)
        return None


def build_trace_url(trace_id: str | None) -> str | None:
    if not trace_id or not settings.langsmith_run_url_prefix:
        return None
    return f"{settings.langsmith_run_url_prefix.rsplit('/')}/r/{trace_id}"