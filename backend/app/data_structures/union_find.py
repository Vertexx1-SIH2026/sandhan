"""
Disjoint Set Union (DSU).

Used in two places:
  1. Case clustering -- every confirmed / verified case link is a union, so
     `groups()` returns the clusters of cases that belong to one network
     (a new case joins the cluster of every historical case it links to).
  2. Person alias resolution -- fuzzy-matched FIR names ("Rahul Kumar" /
     "Rahul Kumaar") are unioned into one identity.
"""
from __future__ import annotations


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def _make(self, key: str) -> None:
        if key not in self.parent:
            self.parent[key] = key
            self.rank[key] = 0

    def add(self, key: str) -> None:
        self._make(key)

    def find(self, key: str) -> str:
        self._make(key)
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[key] != root:          # path compression (iterative)
            self.parent[key], key = root, self.parent[key]
        return root

    def union(self, key_a: str, key_b: str) -> str:
        root_a, root_b = self.find(key_a), self.find(key_b)
        if root_a == root_b:
            return root_a
        if self.rank[root_a] < self.rank[root_b]:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        if self.rank[root_a] == self.rank[root_b]:
            self.rank[root_a] += 1
        return root_a

    def connected(self, a: str, b: str) -> bool:
        return self.find(a) == self.find(b)

    def groups(self) -> list[set[str]]:
        out: dict[str, set[str]] = {}
        for key in self.parent:
            out.setdefault(self.find(key), set()).add(key)
        return sorted(out.values(), key=len, reverse=True)

    def group_of(self, key: str) -> set[str]:
        root = self.find(key)
        return {k for k in self.parent if self.find(k) == root}
