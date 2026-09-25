"""Simple trie for prefix search over phone numbers / IMEIs, used by the
investigator-facing quick-search box on the frontend."""
from __future__ import annotations


class _TrieNode:
    __slots__ = ("children", "entity_ids")

    def __init__(self) -> None:
        self.children: dict[str, "_TrieNode"] = {}
        self.entity_ids: set[str] = set()


class Trie:
    def __init__(self) -> None:
        self.root = _TrieNode()

    def insert(self, key: str, entity_id: str) -> None:
        node = self.root
        for ch in key:
            node = node.children.setdefault(ch, _TrieNode())
            node.entity_ids.add(entity_id)

    def search_prefix(self, prefix: str, limit: int = 25) -> list[str]:
        node = self.root
        for ch in prefix:
            if ch not in node.children:
                return []
            node = node.children[ch]
        return list(node.entity_ids)[:limit]


# Module-level singleton, rebuilt at startup from Neo4j entity nodes.
trie = Trie()
