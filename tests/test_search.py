"""Tests for the full-text search index (adapt.search), the plugin index()
hooks, and the permission-filtered /search endpoint."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from adapt import cache, search
from adapt.app import create_app
from adapt.auth.password import hash_password
from adapt.config import AdaptConfig
from adapt.discovery import discover_resources
from adapt.plugins.base import Plugin, ResourceDescriptor, SearchDocument
from adapt.plugins.html_plugin import HtmlPlugin
from adapt.plugins.markdown_plugin import MarkdownPlugin
from adapt.plugins.python_plugin import PythonHandlerPlugin
from adapt.storage import (
    Action, Group, GroupPermission, Permission, User, UserGroup, init_database,
)


@pytest.fixture(name="indexed_root")
def indexed_root_fixture(tmp_path):
    """A docroot with one resource of each indexable type, wired to a fresh index."""
    root = tmp_path / "docroot"
    (root / "hr").mkdir(parents=True)
    (root / "hr" / "contacts.csv").write_text(
        "name,department,topic\n"
        "Dana Ruiz,Benefits,parental leave\n"
        "Sam Okafor,Payroll,direct deposit\n",
        encoding="utf-8",
    )
    (root / "onboarding.md").write_text(
        "Intro paragraph.\n\n"
        "# Benefits Overview\n\nEligible for parental leave after 90 days.\n\n"
        "## Direct Deposit\n\nSubmit form 12B.\n",
        encoding="utf-8",
    )
    (root / "policy.html").write_text(
        "<html><head><title>Travel Policy</title></head>"
        "<body><script>var x=1;</script><p>Book flights via Concur.</p></body></html>",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("Fire drill is quarterly.\n", encoding="utf-8")

    config = AdaptConfig(root=root)
    init_database(config.db_path)
    cache.configure(str(config.db_path))
    search.configure(str(config.db_path))
    return root, config


class _FakePlugin(Plugin):
    """Minimal plugin that yields a fixed set of documents."""

    def __init__(self, docs):
        self.docs = docs

    def detect(self, path):
        return True

    def load(self, path):
        return ResourceDescriptor(path=path, resource_type="csv")

    def schema(self, resource):
        return {}

    def read(self, resource, request):
        return []

    def write(self, resource, data, request, context):
        raise NotImplementedError

    def index(self, resource):
        return self.docs


class _ExplodingPlugin(_FakePlugin):
    def index(self, resource):
        raise ValueError("plugin blew up")


# --------------------------------------------------------------------------
# Query sanitization
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "C++", 'foo"bar', "AND", "OR NOT ^x", "((", "it's", "深圳 test",
    "a b c d e f g h i j k l m n o p q r s t u v",
])
def test_build_match_query_accepts_hostile_input(indexed_root, raw):
    """Any string must produce a valid MATCH expression or None, never an error."""
    expr = search.build_match_query(raw)
    if expr is not None:
        search.query(expr, limit=5)  # must not raise OperationalError


@pytest.mark.parametrize("raw", ["", "   ", "*", "((", "!!!"])
def test_build_match_query_returns_none_for_tokenless_input(indexed_root, raw):
    assert search.build_match_query(raw) is None


def test_build_match_query_caps_token_count(indexed_root):
    expr = search.build_match_query(" ".join(str(n) for n in range(50)))
    assert expr.count('"') // 2 == search.MAX_QUERY_TOKENS


# --------------------------------------------------------------------------
# Index lifecycle
# --------------------------------------------------------------------------

def test_reindex_is_incremental_then_prunes(indexed_root):
    root, config = indexed_root
    resources = discover_resources(root, config)

    first = search.reindex_all(resources, config)
    assert first["indexed"] == 4
    assert first["documents"] > 4  # csv rows and md sections expand
    assert first["skipped"] == 0

    second = search.reindex_all(resources, config)
    assert second == {"indexed": 0, "skipped": 4, "pruned": 0, "documents": 0}

    (root / "notes.txt").unlink()
    third = search.reindex_all(discover_resources(root, config), config)
    assert third["pruned"] == 1
    assert search.query(search.build_match_query("fire drill")) == []


def test_reindex_force_reindexes_unchanged_files(indexed_root):
    root, config = indexed_root
    resources = discover_resources(root, config)
    search.reindex_all(resources, config)
    forced = search.reindex_all(resources, config, force=True)
    assert forced["indexed"] == 4 and forced["skipped"] == 0


def test_index_replaces_previous_documents(indexed_root):
    root, _ = indexed_root
    path = root / "hr" / "contacts.csv"
    descriptor = ResourceDescriptor(path=path, resource_type="csv")

    search.index_resource(_FakePlugin([SearchDocument("Dana", "topic: sabbatical")]),
                          descriptor, "hr/contacts")
    assert len(search.query(search.build_match_query("sabbatical"))) == 1

    search.index_resource(_FakePlugin([SearchDocument("Dana", "topic: relocation")]),
                          descriptor, "hr/contacts")
    assert search.query(search.build_match_query("sabbatical")) == []
    assert len(search.query(search.build_match_query("relocation"))) == 1


def test_sheets_of_one_workbook_do_not_clobber_each_other(indexed_root):
    """Regression: index state is keyed on (source_path, namespace), not path alone.

    One .xlsx yields a descriptor per sheet. Keying on source_path alone would
    make reindexing Sheet1 delete Sheet2's documents.
    """
    root, _ = indexed_root
    book = root / "workbook.xlsx"
    book.write_text("placeholder", encoding="utf-8")

    for sheet, word in (("Sheet1", "alpha"), ("Sheet2", "beta")):
        search.index_resource(
            _FakePlugin([SearchDocument(sheet, f"budget {word}")]),
            ResourceDescriptor(path=book, resource_type="excel",
                               metadata={"sub_namespace": sheet}),
            f"workbook/{sheet}",
        )

    assert len(search.query(search.build_match_query("budget"))) == 2

    search.index_resource(
        _FakePlugin([SearchDocument("Sheet1", "budget gamma")]),
        ResourceDescriptor(path=book, resource_type="excel",
                           metadata={"sub_namespace": "Sheet1"}),
        "workbook/Sheet1",
    )
    namespaces = {h["namespace"] for h in search.query(search.build_match_query("budget"))}
    assert namespaces == {"workbook/Sheet1", "workbook/Sheet2"}


def test_failing_plugin_does_not_abort_indexing(indexed_root):
    root, _ = indexed_root
    descriptor = ResourceDescriptor(path=root / "notes.txt", resource_type="html")
    assert search.index_resource(_ExplodingPlugin([]), descriptor, "notes") == 0


def test_drop_resource_removes_documents(indexed_root):
    root, config = indexed_root
    search.reindex_all(discover_resources(root, config), config)
    assert search.query(search.build_match_query("concur"))
    search.drop_resource(str(root / "policy.html"), "policy")
    assert search.query(search.build_match_query("concur")) == []


# --------------------------------------------------------------------------
# Querying
# --------------------------------------------------------------------------

def test_query_spans_resource_types_and_builds_urls(indexed_root):
    root, config = indexed_root
    search.reindex_all(discover_resources(root, config), config)

    hits = {h["namespace"]: h for h in search.query(search.build_match_query("parental leave"))}
    assert set(hits) == {"hr/contacts", "onboarding"}
    assert hits["hr/contacts"]["url"] == "/ui/hr/contacts"
    assert hits["hr/contacts"]["doc_ref"] == "1"
    assert hits["onboarding"]["url"] == "/onboarding#benefits-overview"
    assert "<mark>" in hits["onboarding"]["snippet"]


def test_query_type_filter(indexed_root):
    root, config = indexed_root
    search.reindex_all(discover_resources(root, config), config)
    expr = search.build_match_query("parental leave")
    assert len(search.query(expr)) == 2
    assert {h["resource_type"] for h in search.query(expr, types=["markdown"])} == {"markdown"}


def test_query_respects_candidate_cap(indexed_root):
    root, config = indexed_root
    search.reindex_all(discover_resources(root, config), config)
    assert len(search.query(search.build_match_query("a"), limit=10_000)) <= search.MAX_CANDIDATES


# --------------------------------------------------------------------------
# Plugin index() implementations
# --------------------------------------------------------------------------

def test_dataset_index_folds_column_names_into_body(indexed_root):
    root, config = indexed_root
    search.reindex_all(discover_resources(root, config), config)
    # "department" is a column name, not a cell value.
    assert {h["namespace"] for h in search.query(search.build_match_query("department"))} == {"hr/contacts"}


def test_markdown_index_splits_on_headings(indexed_root):
    root, _ = indexed_root
    docs = list(MarkdownPlugin().index(
        ResourceDescriptor(path=root / "onboarding.md", resource_type="markdown")))
    assert [d.doc_ref for d in docs] == [None, "benefits-overview", "direct-deposit"]
    assert docs[0].body == "Intro paragraph."
    assert docs[1].url_suffix == "#benefits-overview"


def test_markdown_index_handles_file_without_headings(tmp_path):
    path = tmp_path / "flat.md"
    path.write_text("Just a paragraph.", encoding="utf-8")
    docs = list(MarkdownPlugin().index(ResourceDescriptor(path=path, resource_type="markdown")))
    assert len(docs) == 1 and docs[0].doc_ref is None


def test_html_index_strips_markup_and_scripts(indexed_root):
    root, _ = indexed_root
    docs = list(HtmlPlugin().index(
        ResourceDescriptor(path=root / "policy.html", resource_type="html")))
    assert len(docs) == 1
    assert docs[0].title == "Travel Policy"
    assert docs[0].body == "Book flights via Concur."
    assert "var x" not in docs[0].body


def test_txt_index_is_verbatim(indexed_root):
    root, _ = indexed_root
    docs = list(HtmlPlugin().index(
        ResourceDescriptor(path=root / "notes.txt", resource_type="html")))
    assert docs[0].body == "Fire drill is quarterly."


def test_python_handlers_are_not_indexable(tmp_path):
    path = tmp_path / "handler.py"
    path.write_text("router = None\n", encoding="utf-8")
    assert list(PythonHandlerPlugin().index(
        ResourceDescriptor(path=path, resource_type="python"))) == []


# --------------------------------------------------------------------------
# /search endpoint
# --------------------------------------------------------------------------

@pytest.fixture(name="search_client")
def search_client_fixture(tmp_path):
    """A client over a docroot with two datasets sharing a search term.

    "parental leave" appears in both public.csv and secret.csv, so a user
    permitted on only one must never see the other.
    """
    root = tmp_path / "docroot"
    root.mkdir()
    (root / "public.csv").write_text(
        "name,topic\nDana Ruiz,parental leave\n", encoding="utf-8")
    (root / "secret.csv").write_text(
        "name,topic\nMallory Vance,parental leave\n", encoding="utf-8")
    (root / "handbook.md").write_text(
        "# Leave Policy\n\nParental leave accrues monthly.\n", encoding="utf-8")

    app = create_app(AdaptConfig(root=root))
    return TestClient(app), app


def _make_user(app, username, password, *, superuser=False, reads=()):
    """Create a user, optionally a superuser, with read permission on `reads`."""
    with Session(app.state.db_engine) as db:
        user = User(username=username, password_hash=hash_password(password),
                    is_superuser=superuser)
        db.add(user)
        db.commit()
        db.refresh(user)

        for namespace in reads:
            perm = Permission(resource=namespace, action=Action.read)
            db.add(perm)
            db.commit()
            db.refresh(perm)
            group = Group(name=f"{namespace}_readonly_{username}")
            db.add(group)
            db.commit()
            db.refresh(group)
            db.add(GroupPermission(group_id=group.id, permission_id=perm.id))
            db.add(UserGroup(user_id=user.id, group_id=group.id))
            db.commit()
        return user


def _login(client, username, password):
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.cookies.update(response.cookies)


def test_search_requires_authentication(search_client):
    client, _ = search_client
    assert client.get("/search", params={"q": "parental"}).status_code == 401


def test_search_never_returns_unpermitted_resources(search_client):
    """The leak test: a term present in both datasets must only surface the
    one the user may read, and `count` must not betray the other's existence."""
    client, app = search_client
    _make_user(app, "narrow", "pw", reads=["public"])
    _login(client, "narrow", "pw")

    body = client.get("/search", params={"q": "parental leave"}).json()

    assert {r["resource"] for r in body["results"]} == {"public"}
    assert body["count"] == 1
    assert body["has_more"] is False
    assert "secret" not in client.get("/search", params={"q": "Mallory"}).text


def test_search_superuser_sees_every_resource(search_client):
    client, app = search_client
    _make_user(app, "root", "pw", superuser=True)
    _login(client, "root", "pw")

    body = client.get("/search", params={"q": "parental leave"}).json()
    assert {r["resource"] for r in body["results"]} == {"public", "secret", "handbook"}
    assert body["count"] == 3


def test_search_results_carry_followable_urls(search_client):
    client, app = search_client
    _make_user(app, "root2", "pw", superuser=True)
    _login(client, "root2", "pw")

    results = {r["resource"]: r for r in
               client.get("/search", params={"q": "parental leave"}).json()["results"]}

    dataset_hit = results["public"]
    assert dataset_hit["ui_url"] == "/ui/public"
    assert dataset_hit["row_id"] == 1
    assert dataset_hit["api_url"].startswith("/api/public/?filter=")
    assert "<mark>" in dataset_hit["snippet"]

    # Markdown deep-links to the heading anchor; it has no row to address.
    assert results["handbook"]["ui_url"] == "/handbook#leave-policy"
    assert "api_url" not in results["handbook"]


def test_search_api_url_actually_resolves_to_the_row(search_client):
    client, app = search_client
    _make_user(app, "root3", "pw", superuser=True)
    _login(client, "root3", "pw")

    hit = next(r for r in client.get("/search", params={"q": "parental leave"}).json()["results"]
               if r["resource"] == "public")
    rows = client.get(hit["api_url"]).json()
    assert len(rows) == 1 and rows[0]["name"] == "Dana Ruiz"


def test_search_type_filter_and_paging(search_client):
    client, app = search_client
    _make_user(app, "root4", "pw", superuser=True)
    _login(client, "root4", "pw")

    csv_only = client.get("/search", params={"q": "parental leave", "type": "csv"}).json()
    assert {r["type"] for r in csv_only["results"]} == {"csv"}

    first = client.get("/search", params={"q": "parental leave", "limit": 1}).json()
    assert first["count"] == 1 and first["has_more"] is True

    last = client.get("/search", params={"q": "parental leave", "limit": 1, "offset": 2}).json()
    assert last["count"] == 1 and last["has_more"] is False


def test_search_without_query_renders_empty_state(search_client):
    """A bare /search — the navbar's empty submission — is a page, not a 422."""
    client, app = search_client
    _make_user(app, "empty", "pw", superuser=True)
    _login(client, "empty", "pw")

    assert client.get("/search").json() == {
        "query": "", "count": 0, "has_more": False, "results": []}

    page = client.get("/search", headers={"accept": "text/html"})
    assert page.status_code == 200
    assert "Enter a term to search" in page.text


def test_search_tokenless_query_returns_empty_envelope(search_client):
    client, app = search_client
    _make_user(app, "root5", "pw", superuser=True)
    _login(client, "root5", "pw")

    response = client.get("/search", params={"q": "***"})
    assert response.status_code == 200
    assert response.json() == {"query": "***", "count": 0, "has_more": False, "results": []}


@pytest.mark.parametrize("raw", ["C++", 'foo"bar', "AND", "OR NOT ^x", "深圳"])
def test_search_endpoint_survives_hostile_queries(search_client, raw):
    client, app = search_client
    _make_user(app, f"u{abs(hash(raw))}", "pw", superuser=True)
    _login(client, f"u{abs(hash(raw))}", "pw")
    assert client.get("/search", params={"q": raw}).status_code == 200


def test_search_html_page_renders_results(search_client):
    client, app = search_client
    _make_user(app, "html_user", "pw", superuser=True)
    _login(client, "html_user", "pw")

    response = client.get("/search", params={"q": "parental leave"},
                          headers={"accept": "text/html"})
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "<mark>parental</mark>" in body
    assert "/ui/public" in body
    assert 'action="/search"' in body


def test_search_html_escapes_untrusted_content(tmp_path):
    """Snippets carry raw docroot text; markup in a cell must not execute."""
    root = tmp_path / "docroot"
    root.mkdir()
    (root / "hostile.csv").write_text(
        'name,note\n"<script>alert(1)</script>",parental leave\n', encoding="utf-8")

    app = create_app(AdaptConfig(root=root))
    client = TestClient(app)
    _make_user(app, "victim", "pw", superuser=True)
    _login(client, "victim", "pw")

    body = client.get("/search", params={"q": "parental leave"},
                      headers={"accept": "text/html"}).text

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
    # The highlight itself still works.
    assert "<mark>parental</mark>" in body


def test_safe_snippet_restores_only_highlight_tags():
    from adapt.routes_search import safe_snippet

    rendered = str(safe_snippet('<b>x</b> <mark>hit</mark> <img src=x onerror=y>'))
    assert rendered.count("<mark>") == 1 and rendered.count("</mark>") == 1
    assert "<b>" not in rendered and "<img" not in rendered
    assert "&lt;b&gt;" in rendered


def test_reindex_command_reports_counts(tmp_path, capsys):
    from adapt.commands.reindex import run_reindex

    root = tmp_path / "docroot"
    root.mkdir()
    (root / "notes.md").write_text("# Title\n\nBody text.\n", encoding="utf-8")

    run_reindex(root)
    assert "Indexed 1 resource(s)" in capsys.readouterr().out

    run_reindex(root)
    assert "Indexed 0 resource(s)" in capsys.readouterr().out

    run_reindex(root, force=True)
    assert "Indexed 1 resource(s)" in capsys.readouterr().out


def test_check_warns_about_reserved_namespace(tmp_path, capsys):
    from adapt.commands.check import run_check

    root = tmp_path / "docroot"
    root.mkdir()
    (root / "search.md").write_text("# Shadow\n", encoding="utf-8")
    (root / "fine.md").write_text("# Fine\n", encoding="utf-8")

    run_check(root)
    out = capsys.readouterr().out
    assert "search.md shadows the built-in /search route" in out
    assert "fine.md" not in out


def test_navbar_search_box_appears_on_content_pages(search_client):
    """The box lives in the shared navbar, so it must reach markdown pages too.

    Regression: markdown_plugin rendered base.html without `user`, which
    silently dropped both the search box and the Profile link.
    """
    client, app = search_client
    _make_user(app, "browser", "pw", superuser=True)
    _login(client, "browser", "pw")

    for path in ("/", "/handbook", "/search"):
        body = client.get(path, headers={"accept": "text/html"}).text
        assert 'action="/search"' in body, f"no search box on {path}"
        # The form needs a real submit control: implicit Enter-to-submit does
        # not reliably fire, and a button-less form is unusable by keyboard.
        form = body.split('action="/search"', 1)[1].split("</form>", 1)[0]
        assert 'type="submit"' in form, f"search box on {path} has no submit button"


def test_search_is_advertised_to_authenticated_users_only(search_client):
    client, app = search_client
    assert "/search" not in client.get("/openapi.json").json()["paths"]

    _make_user(app, "root6", "pw", superuser=True)
    _login(client, "root6", "pw")
    assert "/search" in client.get("/openapi.json").json()["paths"]
