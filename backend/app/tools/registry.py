from typing import Any

from app.tools import weather_tool


class ToolRegistry:
    """集中式工具注册表（单例）。"""

    _instance: "ToolRegistry | None" = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools = [weather_tool.get_weather]
        return cls._instance

    def register(self, tool: Any) -> None:
        self._tools.append(tool)

    def get_tools(self) -> list:
        return list(self._tools)


if __name__ == "__main__":
    a = ToolRegistry()
    b = ToolRegistry()
    assert a is b
    assert a.get_tools()
    print("registry ok")
