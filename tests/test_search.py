"""Tests for the full-text search index (adapt.search) and plugin index() hooks."""
import pytest

from adapt import cache, search
from adapt.config import AdaptConfig
from adapt.discovery import discover_resources
from adapt.plugins.base import Plugin, ResourceDescriptor, SearchDocument
from adapt.plugins.html_plugin import HtmlPlugin
from adapt.plugins.markdown_plugin import MarkdownPlugin
from adapt.plugins.python_plugin import PythonHandlerPlugin
from adapt.storage import init_database


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
