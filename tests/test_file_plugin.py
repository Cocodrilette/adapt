import tempfile
from pathlib import Path

import pytest

from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from adapt.plugins.base import ResourceDescriptor
from adapt.plugins.file_plugin import FilePlugin


@pytest.fixture
def sample_txt():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("line one\nline two\n")
        path = Path(f.name)
    yield path
    path.unlink()


@pytest.fixture
def sample_pdf():
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4\n%test\n")
        path = Path(f.name)
    yield path
    path.unlink()


def test_file_plugin_detect(sample_txt, sample_pdf):
    plugin = FilePlugin()
    assert plugin.detect(sample_txt)
    assert plugin.detect(sample_pdf)
    assert plugin.detect(Path("image.png"))
    assert not plugin.detect(Path("test.md"))


def test_file_plugin_load_sets_mime_metadata(sample_txt):
    plugin = FilePlugin()
    descriptor = plugin.load(sample_txt)
    assert isinstance(descriptor, ResourceDescriptor)
    assert descriptor.path == sample_txt
    assert descriptor.resource_type == "file"
    assert descriptor.metadata["media_type"] == "text/plain"
    assert descriptor.metadata["default_disposition"] == "inline"


def test_file_plugin_read_returns_path(sample_txt):
    plugin = FilePlugin()
    descriptor = plugin.load(sample_txt)
    request = Request(scope={"type": "http", "method": "GET", "path": "/"})
    assert plugin.read(descriptor, request) == str(sample_txt)


def test_file_plugin_write_raises(sample_txt):
    plugin = FilePlugin()
    descriptor = plugin.load(sample_txt)
    with pytest.raises(NotImplementedError):
        plugin.write(descriptor, {}, None, None)


def test_file_plugin_get_route_configs(sample_txt):
    plugin = FilePlugin()
    descriptor = plugin.load(sample_txt)
    configs = plugin.get_route_configs(descriptor)
    assert len(configs) == 1
    prefix, router = configs[0]
    assert prefix == ""
    assert isinstance(router, APIRouter)
    assert len(router.routes) == 1
    route = router.routes[0]
    assert route.path == ""
    assert route.methods == {"GET"}


def test_file_plugin_serves_text_inline(sample_txt):
    plugin = FilePlugin()
    descriptor = plugin.load(sample_txt)
    _, router = plugin.get_route_configs(descriptor)[0]

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/file")
    client = TestClient(app)

    response = client.get("/file")
    assert response.status_code == 200
    assert response.text.splitlines() == ["line one", "line two"]
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith("inline;")


def test_file_plugin_forces_download_with_query_param(sample_pdf):
    plugin = FilePlugin()
    descriptor = plugin.load(sample_pdf)
    _, router = plugin.get_route_configs(descriptor)[0]

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/file")
    client = TestClient(app)

    response = client.get("/file?download=true")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"].startswith("attachment;")
