"""Default registry wiring: the tools every tutor session starts with."""

from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.profile.service import ProfileService
from tutor.tools.content import content_get_source_tool, content_search_tool
from tutor.tools.profile_tools import profile_read_tool, profile_write_tool
from tutor.tools.registry import ToolRegistry


def build_default_registry(settings: TutorSettings | None = None) -> ToolRegistry:
    resolved = settings or TutorSettings.from_env()
    client = OpenNotebookClient(
        base_url=resolved.open_notebook_api_url,
        password=resolved.open_notebook_password,
    )
    service = ProfileService()

    registry = ToolRegistry()
    registry.register(content_search_tool(client))
    registry.register(content_get_source_tool(client))
    registry.register(profile_read_tool(service))
    registry.register(profile_write_tool(service))
    return registry
