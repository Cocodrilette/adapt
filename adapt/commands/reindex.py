from pathlib import Path
import logging

from ..config import AdaptConfig
from ..discovery import discover_resources
from ..storage import init_database
from .. import cache, search

logger = logging.getLogger(__name__)


def run_reindex(root: Path, force: bool = False) -> None:
    """Rebuild the full-text search index for a document root.

    The index normally refreshes on server startup. Run this to rebuild it
    without starting the server, or with `force` after changing how a plugin
    produces documents, since incremental refresh keys only on file mtime and
    size and would otherwise skip unchanged files.

    Args:
        root: The document root to index.
        force: Reindex every resource, even ones that appear unchanged.
    """
    config = AdaptConfig(root=root)
    config.load_from_file()
    init_database(config.db_path)
    cache.configure(str(config.db_path))
    search.configure(str(config.db_path))

    if not search.is_available():
        logger.error("Search index unavailable: this SQLite build lacks FTS5")
        print("Search index unavailable: this SQLite build lacks FTS5.")
        return

    resources = discover_resources(config.root, config)
    stats = search.reindex_all(resources, config, force=force)

    print(f"Document root: {config.root}")
    print(f"Search index: {config.db_path}")
    print(
        f"Indexed {stats['indexed']} resource(s) "
        f"({stats['documents']} document(s)), "
        f"skipped {stats['skipped']}, pruned {stats['pruned']}"
    )
