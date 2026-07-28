"""adapt.plugins.base — Abstract plugin interface and shared plugin utilities."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import errno
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Iterable, Sequence, TYPE_CHECKING

from fastapi import Request
from fastapi.routing import APIRouter
from sqlalchemy import Engine

if TYPE_CHECKING:
    from ..locks import LockManager

logger = logging.getLogger(__name__)


@dataclass
class PluginContext:
    """Context passed to plugins containing shared resources."""
    engine: Engine
    root: Path
    readonly: bool
    lock_manager: "LockManager"


@dataclass
class ResourceDescriptor:
    """Descriptor for a discovered resource."""
    path: Path
    resource_type: str
    schema_path: Path | None = None
    ui_path: Path | None = None
    options_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchDocument:
    """A single unit of indexable content yielded by Plugin.index()."""
    title: str
    body: str
    doc_ref: str | None = None
    url_suffix: str = ""


class Plugin(ABC):
    """Abstract base class for all plugins."""
    
    @abstractmethod
    def detect(self, path: Path) -> bool:
        """Detect if this plugin can handle the given path."""
        ...

    @abstractmethod
    def load(self, path: Path) -> ResourceDescriptor | Sequence[ResourceDescriptor]:
        """Load resource descriptor(s) for the given path."""
        ...

    @abstractmethod
    def schema(self, resource: ResourceDescriptor) -> dict[str, Any]:
        """Return the schema for the resource."""
        return "", {}

    @abstractmethod
    def read(self, resource: ResourceDescriptor, request: Request) -> Any:
        """Read data/content for the resource."""
        ...

    @abstractmethod
    def write(self, resource: ResourceDescriptor, data: Any, request: Request, context: PluginContext) -> Any:
        """Write data/content for the resource."""
        ...

    def apply_options(self, descriptor: ResourceDescriptor) -> None:
        """Apply per-resource options to a descriptor after discovery has located them.

        Options come from the companion `.adapt/<name>[.<sub_namespace>].options.json`
        file and are already parsed into `descriptor.metadata["options"]`. This runs
        after `load()` because `load()` receives only a path and cannot know where the
        companion directory is; it runs before `generate_companion_files()` so that any
        derived schema reflects the options.

        The default does nothing. Plugins override this to honour the options they
        support.
        """
        logger.debug(f"No options to apply for resource: {descriptor.path}")

    def get_route_configs(self, descriptor: ResourceDescriptor) -> list[tuple[str, APIRouter]]:
        """Return list of (prefix, router) tuples for mounting routes."""
        logger.debug(f"Getting route configs for resource: {descriptor.path}")
        return []

    def index(self, resource: ResourceDescriptor) -> Iterable[SearchDocument]:
        """Yield documents for the full-text search index.

        The default returns nothing, so a resource is simply not searchable
        unless its plugin opts in.

        Note that the index is user-agnostic: `filter_for_user` is deliberately
        NOT applied here, because one index is shared by every user. Row-level
        security is enforced when a hit is followed to its API or UI route, and
        resource-level permissions are enforced when results are returned. If a
        plugin's rows are sensitive per-user beyond that, do not index them.
        """
        logger.debug(f"Resource not indexable: {resource.path}")
        return []

    def filter_for_user(self, resource: ResourceDescriptor, user: Any, rows: Iterable[Any]) -> Iterable[Any]:
        """Filter rows based on user context (Row-Level Security).
        
        Default implementation returns all rows. Override this in plugins to implement RLS.
        """
        logger.debug(f"Filtering rows for user on resource: {resource.path}")
        return rows

    def default_ui(self, descriptor: ResourceDescriptor) -> str:
        """Generate a default HTML UI for the resource."""
        logger.debug(f"Generating default UI for resource: {descriptor.path}")
        schema = self.schema(descriptor)
        columns = schema.get('columns', {})
        if isinstance(columns, dict):
            column_names = list(columns.keys())
        else:
            column_names = [col.get('name', 'Column') for col in columns] if columns else []
        columns_html = "".join(f"<th>{name}</th>" for name in column_names)
        
        template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{{ title }}</title>
</head>
<body>
    <h1>{{ title }}</h1>
    <table>
        <thead><tr>{columns_html}</tr></thead>
        <tbody>{{ table_rows }}</tbody>
    </table>
    <script>fetch('{{ api_url }}').then(/* populate rows */);</script>
</body>
</html>
""".strip()
        
        return template.format(columns_html=columns_html)

    def generate_companion_files(self, descriptor: ResourceDescriptor) -> None:
        """Generate companion files for the resource.
        
        Default implementation does nothing. Override in plugins that need companion files.
        """
        logger.debug(f"Generating companion files for resource: {descriptor.path}")
        pass


def discover_plugins(root: Path) -> Iterable[Plugin]:
    """Discover plugin definitions in the document root.

    This placeholder simply yields an empty list; concrete implementations
    should iterate `root.glob(\"*.py\")`, detect routers, and return plugin
    instances.
    """
    logger.debug(f"Discovering plugins in root: {root}")
    return []


def ensure_file(path: Path, content: str) -> None:
    """Ensure a file exists with the given content, creating it if necessary."""
    if path.exists():
        logger.debug("File %s already exists, skipping creation", path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.debug("Created file %s", path)


def atomic_write(target: Path, suffix: str, write_fn: Callable[[Path], None]) -> None:
    """Write via a temp file on the target filesystem with EXDEV fallback."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.stem}.",
        suffix=suffix,
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        write_fn(tmp_path)
        try:
            os.replace(tmp_path, target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            shutil.copyfile(tmp_path, target)
            tmp_path.unlink()
    finally:
        tmp_path.unlink(missing_ok=True)
