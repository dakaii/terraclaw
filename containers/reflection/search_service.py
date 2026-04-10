from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any


class SearchProvider(ABC):
    """Abstract interface for web search providers."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Perform a search and return a list of results."""
        pass


class TavilyProvider(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        # In a real app, you'd use a client like `tavily-python`

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        print(f"[Tavily] Searching for: {query}")
        # Dummy implementation
        return [{"title": "Example Result", "url": "https://example.com", "content": "..."}]


class SerperProvider(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        print(f"[Serper] Searching for: {query}")
        # Dummy implementation
        return [{"title": "Serper Result", "link": "https://serper.dev", "snippet": "..."}]


def get_search_provider() -> SearchProvider:
    """Factory to get the configured search provider."""
    provider_type = os.environ.get("SEARCH_PROVIDER", "tavily").lower()

    if provider_type == "tavily":
        return TavilyProvider(os.environ.get("TAVILY_API_KEY", "dummy"))
    elif provider_type == "serper":
        return SerperProvider(os.environ.get("SERPER_API_KEY", "dummy"))
    else:
        raise ValueError(f"Unknown search provider: {provider_type}")
