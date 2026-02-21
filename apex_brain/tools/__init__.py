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
            continue  # base is imported separately
        importlib.import_module(f"tools.{module_name}")

    # Hide deprecated wrapper tools from the LLM.
    # They remain callable (backward-compat) but are not advertised,
    # reducing tool count from ~70 to ~30 for reliable tool selection.
    from tools.base import DEPRECATED_TOOLS, TOOL_REGISTRY, hide_tools

    hide_tools(*DEPRECATED_TOOLS)
    visible = sum(
        1 for t in TOOL_REGISTRY.values() if not t.get("hidden")
    )
    logger.info(
        "Tools: %d registered, %d visible to LLM, %d hidden (deprecated)",
        len(TOOL_REGISTRY),
        visible,
        len(TOOL_REGISTRY) - visible,
    )
