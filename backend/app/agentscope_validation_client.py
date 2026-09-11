"""Transport for the platform-owned validation MCP and its version metadata."""
from typing import Any


class InitializationValidationClientMixin:
    def get_initialization_validation_binding(self) -> dict[str, Any] | None:
        from .agentscope_client import AgentScopeGatewayError

        result = self._request("POST", "/mcp-registry/platform/project-initialization-validation",
                               json={"metadata_only": True})
        if not isinstance(result, dict) or result.get("metadata_only") is not True:
            raise AgentScopeGatewayError("核验服务尚未支持快照版本查询，请更新服务。")
        return {key: result[key] for key in ("package_id", "package_version")}

    def validate_project_initialization(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the active platform validation MCP without an LLM turn."""
        from .agentscope_client import AgentScopeGatewayError

        result = self._request(
            "POST",
            "/mcp-registry/platform/project-initialization-validation",
            json={"payload": payload},
        )
        if not isinstance(result, dict):
            raise AgentScopeGatewayError("项目初始化核验 MCP 返回格式无效。")
        return result
