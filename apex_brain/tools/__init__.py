# Auto-discover all tool modules in this package
import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)


def discover_tools():
    """Import all modules in the tools package to register @tool functions."""
    package_dir = Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
        if module_name == "base":
            continue
        importlib.import_module(f"tools.{module_name}")

    from tools.base import TOOL_REGISTRY

    visible = sum(1 for t in TOOL_REGISTRY.values() if not t.get("hidden"))
    logger.info(
        "Tools: %d registered, %d visible to LLM",
        len(TOOL_REGISTRY),
        visible,
    )
