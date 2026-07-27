from pathlib import Path
import logging

from ..config import AdaptConfig
from ..discovery import discover_resources
from ..storage import init_database
from .. import cache

logger = logging.getLogger(__name__)

# Namespaces claimed by built-in routes. A markdown or HTML file with one of
# these names mounts at the same path and shadows the built-in.
RESERVED_NAMESPACES = frozenset({
    "search", "health", "profile", "admin", "docs", "static", "openapi.json",
})


def run_check(root: Path) -> None:
    """Check the configuration and discover resources.

    Args:
        root: The root directory path for the Adapt configuration.

    Returns:
        None

    Raises:
        None
    """
    config = AdaptConfig(root=root)
    config.load_from_file()
    engine = init_database(config.db_path)
    cache.configure(str(config.db_path))
    resources = discover_resources(config.root, config)
    count = len(resources)
    logger.info("Discovered %d dataset(s) in root %s", count, config.root)
    print(f"Document root: {config.root}")
    print(f"SQLite store: {config.db_path} (engine {engine})")
    print(f"Discovered {count} dataset(s)")

    # Markdown and HTML resources mount at /<namespace>, so they can collide
    # with built-in routes; datasets live under /api and /ui and cannot.
    for resource in resources:
        if resource.resource_type not in ("markdown", "html"):
            continue
        namespace = resource.relative_path.with_suffix("").as_posix()
        if namespace in RESERVED_NAMESPACES:
            logger.warning("Resource %s shadows the built-in /%s route", resource.path, namespace)
            print(f"WARNING: {resource.relative_path} shadows the built-in /{namespace} route")
    # Validate TLS if configured
    if config.tls_cert or config.tls_key:
        if config.tls_cert and not config.tls_cert.exists():
            logger.warning("TLS cert file does not exist: %s", config.tls_cert)
        if config.tls_key and not config.tls_key.exists():
            logger.warning("TLS key file does not exist: %s", config.tls_key)
        if config.tls_cert and config.tls_key:
            logger.info("TLS configured with cert: %s, key: %s", config.tls_cert, config.tls_key)
        else:
            logger.warning("TLS partially configured; both cert and key required")