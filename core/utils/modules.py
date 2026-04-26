"""
Lazy module loaders for optional dependencies.
可选依赖的懒加载器。
"""

from __future__ import annotations

import importlib
from typing import Any


def load_module(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Required dependency '%s' is not installed in the active Python environment"
            % module_name
        ) from exc


def feedparser_module() -> Any:
    return load_module("feedparser")


def trafilatura_module() -> Any:
    return load_module("trafilatura")


def readability_document_class() -> Any:
    return load_module("readability").Document


def email_client_class() -> Any:
    return load_module("azure.communication.email").EmailClient
