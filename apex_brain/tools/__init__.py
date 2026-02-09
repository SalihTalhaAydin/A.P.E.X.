# Auto-discover all tool modules in this package
import importlib
import pkgutil
from pathlib import Path

def discover_tools():
    """Import all modules in the tools package to register @tool functions."""
    package_dir = Path(__file__).parent
    for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
        if module_name == "base":
            continue  # base is imported separately
        importlib.import_module(f"tools.{module_name}")
