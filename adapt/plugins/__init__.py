import logging

logger = logging.getLogger(__name__)

from .base import Plugin, PluginContext, ResourceDescriptor, discover_plugins
from .csv_plugin import CsvPlugin
from .excel_plugin import ExcelPlugin
from .file_plugin import FilePlugin
from .media_plugin import MediaPlugin
from .python_plugin import PythonHandlerPlugin

logger.debug("Plugins module initialized")

__all__ = [
    "Plugin",
    "PluginContext",
    "ResourceDescriptor",
    "discover_plugins",
    "CsvPlugin",
    "ExcelPlugin",
    "FilePlugin",
    "MediaPlugin",
    "PythonHandlerPlugin",
]
