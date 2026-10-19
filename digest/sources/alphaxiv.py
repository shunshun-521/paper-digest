"""alphaXiv MCP client. Schemas come from list_tools(), never hardcoded."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from tenacity import retry, stop_after_attempt, wait_exponential

from digest.ids import extract_arxiv_ids

logger = logging.getLogger(__name__)

ALPHAXIV_MCP_URL = "https://api.alphaxiv.org/mcp/v1"
FEED_TOOLS = {
    "for_you": "get_for_you_feed",
    "hot": "get_hot_feed",
}
CONTENT_TOOL = "get_paper_content"
LIMIT_KEYS = (
    "limit",
    "count",
    "n",
    "max_results",
    "maxResults",
    "page_size",
    "pageSize",
    "num",
    "size",
    "top_k",
    "topK",
)
ID_KEYS = ("arxiv_id", "paper_id", "id", "paperId", "arxivId", "paper")

ToolCaller = Callable[[str, dict[str, Any]], Awaitable[str]]


def build_tool_arguments(schema: dict[str, Any] | None, *, kind: str, arxiv_id: str | None = None) -> dict[str, Any]:
    """Build arguments from the tool's inputSchema. Unknown schemas get no guessed keys."""
    schema = schema or {}
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        properties = {}
    args: dict[str, Any] = {}
    if kind == "feed":
        for key in LIMIT_KEYS:
            if key in properties:
                spec = properties.get(key) or {}
                maximum = spec.get("maximum") if isinstance(spec, dict) else None
                limit = 30
                if isinstance(maximum, int):
                    limit = min(limit, maximum)
                args[key] = limit
                break
    elif kind == "content":
        chosen = next((key for key in ID_KEYS if key in properties), None)
        if chosen and arxiv_id:
            args[chosen] = arxiv_id
    return args


def tool_result_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    chunks: list[str] = []
    if content:
        for block in content:
            text = getattr(block, "text", None)
            if text:
                chunks.append(text)
    if chunks:
        return "".join(chunks)
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured is not None:
        import json

        return json.dumps(structured, ensure_ascii=False)
    return str(result)


class AlphaXivClient:
    """One MCP session per run. Tests inject ``caller`` and ``schemas``."""

    def __init__(
        self,
        api_key: str | None,
        *,
        caller: ToolCaller | None = None,
        schemas: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key
        self._caller = caller
        self._schemas = schemas
        self._session_cm = None
        self._client_cm = None
        self._http_cm = None

    @property
    def available(self) -> bool:
        return bool(self.api_key) or self._caller is not None

    async def __aenter__(self) -> "AlphaXivClient":
        if self._caller is not None or not self.api_key:
            return self
        import httpx2
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        self._http_cm = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx2.Timeout(30.0),
        )
        http_client = await self._http_cm.__aenter__()
        self._client_cm = streamable_http_client(ALPHAXIV_MCP_URL, http_client=http_client)
        read_stream, write_stream = await self._client_cm.__aenter__()
        self._session_cm = ClientSession(read_stream, write_stream)
        session = await self._session_cm.__aenter__()
        await session.initialize()

        async def call(name: str, args: dict[str, Any]) -> str:
            result = await session.call_tool(name, args, read_timeout_seconds=30)
            return tool_result_text(result)

        self._caller = call
        listed = await session.list_tools()
        self._schemas = {}
        for tool in listed.tools:
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
            self._schemas[tool.name] = schema if isinstance(schema, dict) else {}
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session_cm is not None:
            await self._session_cm.__aexit__(exc_type, exc, tb)
        if self._client_cm is not None:
            await self._client_cm.__aexit__(exc_type, exc, tb)
        if self._http_cm is not None:
            await self._http_cm.__aexit__(exc_type, exc, tb)

    def schema_for(self, name: str) -> dict[str, Any]:
        if not self._schemas:
            return {}
        return self._schemas.get(name) or {}

    async def _call(self, name: str, args: dict[str, Any]) -> str:
        if self._caller is None:
            raise RuntimeError("alphaXiv session is not open")

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            reraise=True,
        )
        async def _once() -> str:
            return await self._caller(name, args)  # type: ignore[misc]

        return await _once()

    async def feed_ids(self, which: str) -> list[str]:
        tool = FEED_TOOLS[which]
        args = build_tool_arguments(self.schema_for(tool), kind="feed")
        text = await self._call(tool, args)
        return extract_arxiv_ids(text)

    async def paper_content(self, arxiv_id: str) -> str:
        schema = self.schema_for(CONTENT_TOOL)
        args = build_tool_arguments(schema, kind="content", arxiv_id=arxiv_id)
        if schema and not args:
            raise RuntimeError("get_paper_content schema has no recognizable id field")
        if not schema:
            raise RuntimeError("get_paper_content schema unavailable")
        return await self._call(CONTENT_TOOL, args)
