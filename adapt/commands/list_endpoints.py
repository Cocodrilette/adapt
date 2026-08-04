from pathlib import Path
import logging

from fastapi import FastAPI

from .. import cache
from ..config import AdaptConfig
from ..discovery import discover_resources
from ..routes import build_resource_registry, generate_routes, iter_effective_routes
from ..storage import init_database

logger = logging.getLogger(__name__)


def run_list_endpoints(root: Path) -> None:
    """List the resource endpoints that Adapt actually generates.

    Args:
        root: The root directory path for the Adapt configuration.

    Returns:
        None

    Raises:
        None
    """
    config = AdaptConfig(root=root)
    config.load_from_file()
    init_database(config.db_path)
    cache.configure(str(config.db_path))
    resources = discover_resources(config.root, config)
    if not resources:
        logger.info("No resources discovered in root %s", config.root)
        print("No resources discovered.")
        return

    # Build the same registry and mount the same plugin routers as create_app().
    # Inferring routes from resource types drifts from plugin behavior: it misses
    # sub-resources and reports routes that a plugin never mounted.
    app = FastAPI()
    registry = build_resource_registry(resources, config)
    generate_routes(app, registry)
    paths = {
        path.rstrip("/") or "/"
        for path, _route in iter_effective_routes(app.routes)
    }

    logger.debug(
        "Listing %d generated endpoints for %d resources", len(paths), len(resources)
    )
    if not paths:
        print("No endpoints generated.")
        return
    for path in sorted(paths):
        print(path)
