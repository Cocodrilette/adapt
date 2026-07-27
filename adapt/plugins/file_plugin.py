from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRouter

from .base import Plugin, PluginContext, ResourceDescriptor, SearchDocument


logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {
    ".txt",
    ".pdf",
    ".json",
    ".xml",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}


def _guess_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(str(path))
    return media_type or "application/octet-stream"


def _is_textual_media_type(media_type: str) -> bool:
    return (
        media_type.startswith("text/")
        or media_type in {"application/json", "application/xml", "image/svg+xml"}
    )


def _content_disposition(filename: str, disposition: str) -> str:
    quoted = quote(filename)
    return f"{disposition}; filename*=UTF-8''{quoted}"


class FilePlugin(Plugin):
    def detect(self, path: Path) -> bool:
        """Detect if the path is a supported browser-displayable file."""
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def load(self, path: Path) -> ResourceDescriptor:
        """Load a generic file resource with MIME metadata."""
        media_type = _guess_media_type(path)
        disposition = "inline" if media_type != "application/octet-stream" else "attachment"
        return ResourceDescriptor(
            path=path,
            resource_type="file",
            metadata={
                "media_type": media_type,
                "default_disposition": disposition,
            },
        )

    def schema(self, resource: ResourceDescriptor) -> dict[str, Any]:
        """Generic files have no structured schema."""
        return {}

    def read(self, resource: ResourceDescriptor, request: Request) -> Any:
        """Return the file path for direct file responses."""
        return str(resource.path)

    def write(self, resource: ResourceDescriptor, data: Any, request: Request, context: PluginContext) -> Any:
        """Write operation is not supported for generic files."""
        logger.warning("Attempted write operation on generic file: %s", resource.path)
        raise NotImplementedError("Generic files do not support write operations")

    def index(self, resource: ResourceDescriptor) -> Sequence[SearchDocument]:
        """Index raw text for textual files only."""
        media_type = resource.metadata.get("media_type", "application/octet-stream")
        if not _is_textual_media_type(media_type):
            return []

        body = resource.path.read_text(encoding="utf-8", errors="replace").strip()
        if not body:
            return []
        return [SearchDocument(title=resource.path.stem, body=body)]

    def get_route_configs(self, descriptor: ResourceDescriptor) -> list[tuple[str, APIRouter]]:
        """Serve files directly at their resource URL."""
        router = APIRouter()

        @router.get("")
        def get_file(request: Request, download: bool = False):
            file_path = self.read(descriptor, request)
            disposition = "attachment" if download else descriptor.metadata.get("default_disposition", "inline")
            headers = {
                "Content-Disposition": _content_disposition(descriptor.path.name, disposition),
            }
            return FileResponse(
                file_path,
                media_type=descriptor.metadata.get("media_type", "application/octet-stream"),
                headers=headers,
            )

        return [("", router)]
