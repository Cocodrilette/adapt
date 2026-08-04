"""Regression tests for the DataTables template against awkward column names.

Column names come from spreadsheet headers, so they are arbitrary text. Rendering
them into JavaScript expressions used to produce a syntax error that killed the
whole script block -- and with it the DataTable init -- leaving a header row and
no data, with nothing in the console pointing at the cause.
"""
import json
import re
import shutil
import subprocess

import pytest
from jinja2 import Environment, FileSystemLoader

from adapt.plugins import dataset_plugin

TEMPLATE_DIR = dataset_plugin.Path(dataset_plugin.__file__).parent.parent / "templates"

# Every one of these has broken, or would break, naive interpolation.
HOSTILE_COLUMNS = [
    "Pipeline Dashboard (auto-calculated)",  # spaces + parentheses: the reported bug
    "Q1.Revenue",                            # DataTables object notation
    "total's",                               # terminates a single-quoted literal
    'say "hi"',                              # terminates a double-quoted literal
    "2024",                                  # not a valid identifier
    "rate-per-hour",                         # parsed as subtraction
    "count()",                               # DataTables function notation
    "back\\slash",
    "</script>",                             # must not break out of the script block
]


def _render(columns, readonly=False):
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("datatable.html")
    schema = {
        "type": "object",
        "name": "hostile",
        "primary_key": "_row_id",
        "columns": {name: {"type": "string"} for name in columns},
    }
    return template.render(
        schema=schema,
        readonly=readonly,
        api_url="/api/hostile",
        title="hostile",
        table_rows="",
        request=None,
        user=None,
        is_superuser=False,
        ui_links=[],
    )


def _script_body(html):
    """Concatenate the page's own inline scripts, skipping CDN <script src> tags."""
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.DOTALL)
    assert blocks, "no inline script found in rendered template"
    return "\n".join(blocks)


@pytest.mark.parametrize("readonly", [False, True])
def test_hostile_column_names_render_valid_javascript(tmp_path, readonly):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is required to syntax-check the rendered script")

    script = _script_body(_render(HOSTILE_COLUMNS, readonly=readonly))
    script_file = tmp_path / "rendered.js"
    script_file.write_text(script, encoding="utf-8")

    result = subprocess.run(
        [node, "--check", str(script_file)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("readonly", [False, True])
def test_column_names_reach_javascript_only_as_json_data(readonly):
    """No column name may appear as a bare identifier in an expression."""
    script = _script_body(_render(HOSTILE_COLUMNS, readonly=readonly))

    match = re.search(r"const COLUMNS = (\[.*?\]);", script, re.DOTALL)
    assert match, "COLUMNS payload not found"
    assert json.loads(match.group(1)) == HOSTILE_COLUMNS

    # Outside that one JSON literal, the names must not appear in actual code.
    remainder = re.sub(r"//[^\n]*", "", script.replace(match.group(1), ""))
    for name in HOSTILE_COLUMNS:
        assert name not in remainder, f"{name!r} leaked into JavaScript code"


def test_readonly_pages_ship_no_write_controls():
    """Write markup is gated in Jinja, so it is absent rather than merely unreachable."""
    readonly_html = _render(HOSTILE_COLUMNS, readonly=True)
    assert "btn-warning" not in readonly_html
    assert "editRecord" not in readonly_html

    writable_html = _render(HOSTILE_COLUMNS, readonly=False)
    assert "btn-warning" in writable_html
    assert "editRecord" in writable_html


def test_form_inputs_use_index_based_ids_and_raw_names():
    """HTML ids cannot contain spaces, but form field names can be anything."""
    html = _render(HOSTILE_COLUMNS, readonly=False)

    for index in range(len(HOSTILE_COLUMNS)):
        assert f'id="edit_col_{index}"' in html
        assert f'id="create_col_{index}"' in html

    # The name attribute still carries the real column, HTML-escaped.
    assert 'name="Pipeline Dashboard (auto-calculated)"' in html
    assert 'name="say &#34;hi&#34;"' in html or 'name="say &quot;hi&quot;"' in html


def test_mutation_failures_display_server_detail():
    script = _script_body(_render(["name", "age"], readonly=False))

    assert "alert(mutationError(result, 'Error creating record'))" in script
    assert "alert(mutationError(result, 'Error updating record'))" in script
    assert "typeof result.detail === 'string'" in script


def test_preserved_legacy_template_gets_detailed_mutation_errors():
    legacy = """
    .then(result => {
        if (result.success) { reload(); }
        else { alert('Error creating record'); }
    })
    .catch(error => { alert('Error creating record'); });
    """

    upgraded = dataset_plugin.DatasetPlugin._inject_mutation_error_details(legacy)

    assert "typeof result.detail === 'string'" in upgraded
    assert upgraded.count("alert('Error creating record');") == 1


def test_script_block_cannot_be_broken_out_of():
    html = _render(["</script><script>alert(1)</script>"])
    assert "<script>alert(1)</script>" not in html
