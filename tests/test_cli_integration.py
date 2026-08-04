from fastapi.testclient import TestClient

from adapt.app import create_app
from adapt.commands.admin import run_create_permissions
from adapt.commands.check import run_check
from adapt.commands.list_endpoints import run_list_endpoints
from adapt.config import AdaptConfig


def _seed_workspace(root):
    # Include a media extension to exercise MediaPlugin cache reads during discovery.
    (root / "data.csv").write_text("name,age\nAlice,30\nBob,25\n")
    (root / "clip.mp3").write_bytes(b"not-a-real-mp3")


def test_run_check_discovers_media_without_cache_table_error(tmp_path, capsys):
    _seed_workspace(tmp_path)

    run_check(tmp_path)

    output = capsys.readouterr().out
    assert "Document root:" in output
    assert "Discovered" in output


def test_run_list_endpoints_discovers_media_without_cache_table_error(tmp_path, capsys):
    _seed_workspace(tmp_path)

    run_list_endpoints(tmp_path)

    output = capsys.readouterr().out
    assert "/api/data" in output


def test_run_list_endpoints_lists_file_resources_as_top_level(tmp_path, capsys):
    (tmp_path / "notes.txt").write_text("hello")

    run_list_endpoints(tmp_path)

    output = capsys.readouterr().out
    assert "/notes" in output
    assert "/api/notes" not in output
    assert "/ui/notes" not in output


def test_run_list_endpoints_uses_mounted_plugin_routes(tmp_path, capsys):
    """List sheet routes and omit guessed routes for Python files with no router."""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.title = "North"
    workbook.active.append(["name"])
    workbook.create_sheet("South").append(["name"])
    workbook.save(tmp_path / "regions.xlsx")

    package = tmp_path / "commands" / "admin"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("# Package marker, not an endpoint.\n")

    run_list_endpoints(tmp_path)

    paths = set(capsys.readouterr().out.splitlines())
    assert "/api/regions/North" in paths
    assert "/schema/regions/South" in paths
    assert "/ui/regions.xlsx/North" in paths
    assert not any("commands/admin/__init__" in path for path in paths)

    app = create_app(
        AdaptConfig(root=tmp_path, search_on_startup=False, mcp_enabled=False)
    )
    client = TestClient(app)
    assert client.get("/schema/regions/South").status_code != 404
    assert client.get("/schema/commands/admin/__init__").status_code == 404


def test_run_list_endpoints_lists_custom_python_router_paths(tmp_path, capsys):
    handler = tmp_path / "hello.py"
    handler.write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n"
        "@router.get('/world')\n"
        "def world():\n"
        "    return {'hello': 'world'}\n"
    )

    run_list_endpoints(tmp_path)

    paths = set(capsys.readouterr().out.splitlines())
    assert "/api/hello/world" in paths
    assert "/api/hello.py/world" in paths
    assert "/schema/hello" not in paths
    assert "/ui/hello" not in paths


def test_run_check_warns_on_reserved_namespace_for_file_resources(tmp_path, capsys):
    (tmp_path / "health.txt").write_text("ok")

    run_check(tmp_path)

    output = capsys.readouterr().out
    assert "shadows the built-in /health route" in output


def test_run_create_permissions_all_with_media_does_not_crash(tmp_path, capsys):
    _seed_workspace(tmp_path)

    run_create_permissions(
        root=tmp_path,
        resources=["__all__"],
        all_group_name="all-rw",
        read_group_name="all-ro",
    )

    output = capsys.readouterr().out
    assert "Using all" in output
    assert "Permissions and groups created successfully." in output
