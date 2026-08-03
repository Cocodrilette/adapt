import json
import logging
import os
from pathlib import Path

import uvicorn

from ..config import AdaptConfig
from ..app import create_app

logger = logging.getLogger(__name__)

_RELOAD_OPTIONS_ENV = "_ADAPT_RELOAD_OPTIONS"


def create_reload_app():
    """Create the application in a Uvicorn reload worker."""
    raw_options = os.environ.get(_RELOAD_OPTIONS_ENV)
    if raw_options is None:
        raise RuntimeError("Adapt reload options are not available")

    options = json.loads(raw_options)
    config = AdaptConfig(root=Path(options["root"]))
    config.load_from_file()
    if options["readonly"] is not None:
        config.readonly = options["readonly"]
    if options["debug"] is not None:
        config.debug = options["debug"]
    config.secure_cookies = options["secure_cookies"]
    return create_app(config)


def run_serve(
    root: Path,
    host: str | None,
    port: int | None,
    tls_cert: str | None,
    tls_key: str | None,
    reload: bool,
    readonly: bool | None,
    debug: bool | None,
) -> None:
    """Start the Adapt server.

    Args:
        root: The root directory path for the Adapt configuration.
        host: The host address to bind the server to.
        port: The port number to bind the server to.
        tls_cert: Path to the TLS certificate file. Optional.
        tls_key: Path to the TLS key file. Optional.
        reload: Whether to enable auto-reload for development.
        readonly: Whether to run the server in read-only mode.

    Returns:
        None

    Raises:
        None
    """
    config = AdaptConfig(root=root)
    config.load_from_file()
    if host is not None:
        config.host = host
    if port is not None:
        config.port = port
    if readonly is not None:
        config.readonly = readonly
    if debug is not None:
        config.debug = debug
    if (tls_cert and not tls_key) or (tls_key and not tls_cert):
        raise ValueError("Both --tls-cert and --tls-key must be provided together")

    if tls_cert:
        config.tls_cert = Path(tls_cert)
    if tls_key:
        config.tls_key = Path(tls_key)

    if config.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    use_tls = bool(config.tls_cert and config.tls_key)
    config.secure_cookies = use_tls  # Set secure cookies when using TLS
    logger.info(
        "Starting server on %s:%d with TLS=%s, reload=%s, readonly=%s, debug=%s",
        config.host,
        config.port,
        use_tls,
        reload,
        config.readonly,
        config.debug,
    )
    app = create_app(config) if not reload else "adapt.commands.serve:create_reload_app"
    reload_options = json.dumps(
        {
            "root": str(root.resolve()),
            "readonly": readonly,
            "debug": debug,
            "secure_cookies": use_tls,
        }
    )
    previous_reload_options = os.environ.get(_RELOAD_OPTIONS_ENV)
    if reload:
        os.environ[_RELOAD_OPTIONS_ENV] = reload_options

    try:
        uvicorn.run(
            app=app,
            host=config.host,
            port=config.port,
            reload=reload,
            reload_dirs=[str(root.resolve())] if reload else None,
            factory=reload,
            ssl_certfile=str(config.tls_cert) if use_tls else None,
            ssl_keyfile=str(config.tls_key) if use_tls else None,
            log_level="debug" if config.debug else "info",
        )
    finally:
        if reload:
            if previous_reload_options is None:
                os.environ.pop(_RELOAD_OPTIONS_ENV, None)
            else:
                os.environ[_RELOAD_OPTIONS_ENV] = previous_reload_options
