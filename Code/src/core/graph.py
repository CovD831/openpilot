"""Graph data structure for OpenPilot.

This module provides a flexible, reusable graph data structure for:
- Memory vault relationships
- Task dependency graphs
- Agent orchestration
"""

from __future__ import annotations

import json
import pickle
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar


class GraphType(str, Enum):
    """Graph type enumeration."""
    DIRECTED = "directed"
    UNDIRECTED = "undirected"


@dataclass
class GraphNode:
    """Node in a graph structure."""

    id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert node to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        """Create node from dictionary."""
        return cls(**data)

    def update(self, data: dict[str, Any] | None = None, attributes: dict[str, Any] | None = None) -> None:
        """Update node data and attributes."""
        if data:
            self.data.update(data)
        if attributes:
            self.attributes.update(attributes)
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class GraphEdge:
    """Edge in a graph structure."""

    source_id: str
    target_id: str
    edge_type: str = "default"
    weight: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert edge to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphEdge:
        """Create edge from dictionary."""
        return cls(**data)

    def reverse(self) -> GraphEdge:
        """Create a reversed edge."""
        return GraphEdge(
            source_id=self.target_id,
            target_id=self.source_id,
            edge_type=self.edge_type,
            weight=self.weight,
            attributes=self.attributes.copy()
        )


T = TypeVar('T')


class Graph:
    """Generic graph data structure with support for directed and undirected graphs."""

    def __init__(self, graph_type: GraphType = GraphType.DIRECTED):
        """Initialize graph.

        Args:
            graph_type: Type of graph (directed or undirected)
        """
        self.graph_type = graph_type
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, list[GraphEdge]] = {}  # source_id -> list of edges
        self._reverse_edges: dict[str, list[GraphEdge]] = {}  # target_id -> list of edges (for directed graphs)

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph.

        Args:
            node: Node to add
        """
        self._nodes[node.id] = node
        if node.id not in self._edges:
            self._edges[node.id] = []
        if node.id not in self._reverse_edges:
            self._reverse_edges[node.id] = []

    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge to the graph.

        Args:
            edge: Edge to add

        Raises:
            ValueError: If source or target node doesn't exist
        """
        if edge.source_id not in self._nodes:
            raise ValueError(f"Source node {edge.source_id} does not exist")
        if edge.target_id not in self._nodes:
            raise ValueError(f"Target node {edge.target_id} does not exist")

        self._edges[edge.source_id].append(edge)
        self._reverse_edges[edge.target_id].append(edge)

        # For undirected graphs, add reverse edge
        if self.graph_type == GraphType.UNDIRECTED:
            reverse_edge = edge.reverse()
            self._edges[edge.target_id].append(reverse_edge)
            self._reverse_edges[edge.source_id].append(reverse_edge)

    def get_node(self, node_id: str) -> GraphNode | None:
        """Get a node by ID.

        Args:
            node_id: Node ID

        Returns:
            Node if found, None otherwise
        """
        return self._nodes.get(node_id)

    def get_edge(self, source_id: str, target_id: str, edge_type: str | None = None) -> GraphEdge | None:
        """Get an edge between two nodes.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            edge_type: Optional edge type filter

        Returns:
            Edge if found, None otherwise
        """
        edges = self._edges.get(source_id, [])
        for edge in edges:
            if edge.target_id == target_id:
                if edge_type is None or edge.edge_type == edge_type:
                    return edge
        return None

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all its edges.

        Args:
            node_id: Node ID to remove

        Returns:
            True if node was removed, False if not found
        """
        if node_id not in self._nodes:
            return False

        # Remove all edges connected to this node
        del self._nodes[node_id]
        del self._edges[node_id]
        del self._reverse_edges[node_id]

        # Remove edges pointing to this node
        for edges in self._edges.values():
            edges[:] = [e for e in edges if e.target_id != node_id]

        for edges in self._reverse_edges.values():
            edges[:] = [e for e in edges if e.source_id != node_id]

        return True

    def remove_edge(self, source_id: str, target_id: str, edge_type: str | None = None) -> bool:
        """Remove an edge.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            edge_type: Optional edge type filter

        Returns:
            True if edge was removed, False if not found
        """
        if source_id not in self._edges:
            return False

        edges = self._edges[source_id]
        original_len = len(edges)

        # Remove matching edges
        self._edges[source_id] = [
            e for e in edges
            if not (e.target_id == target_id and (edge_type is None or e.edge_type == edge_type))
        ]

        # Remove from reverse edges
        if target_id in self._reverse_edges:
            self._reverse_edges[target_id] = [
                e for e in self._reverse_edges[target_id]
                if not (e.source_id == source_id and (edge_type is None or e.edge_type == edge_type))
            ]

        # For undirected graphs, remove reverse edge
        if self.graph_type == GraphType.UNDIRECTED and target_id in self._edges:
            self._edges[target_id] = [
                e for e in self._edges[target_id]
                if not (e.target_id == source_id and (edge_type is None or e.edge_type == edge_type))
            ]
            if source_id in self._reverse_edges:
                self._reverse_edges[source_id] = [
                    e for e in self._reverse_edges[source_id]
                    if not (e.source_id == target_id and (edge_type is None or e.edge_type == edge_type))
                ]

        return len(self._edges[source_id]) < original_len

    def get_neighbors(self, node_id: str, edge_type: str | None = None) -> list[GraphNode]:
        """Get neighboring nodes.

        Args:
            node_id: Node ID
            edge_type: Optional edge type filter

        Returns:
            List of neighboring nodes
        """
        if node_id not in self._edges:
            return []

        edges = self._edges[node_id]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]

        neighbors = []
        for edge in edges:
            node = self.get_node(edge.target_id)
            if node:
                neighbors.append(node)

        return neighbors

    def get_predecessors(self, node_id: str, edge_type: str | None = None) -> list[GraphNode]:
        """Get predecessor nodes (nodes with edges pointing to this node).

        Args:
            node_id: Node ID
            edge_type: Optional edge type filter

        Returns:
            List of predecessor nodes
        """
        if node_id not in self._reverse_edges:
            return []

        edges = self._reverse_edges[node_id]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]

        predecessors = []
        for edge in edges:
            node = self.get_node(edge.source_id)
            if node:
                predecessors.append(node)

        return predecessors

    def get_all_nodes(self) -> list[GraphNode]:
        """Get all nodes in the graph.

        Returns:
            List of all nodes
        """
        return list(self._nodes.values())

    def get_all_edges(self) -> list[GraphEdge]:
        """Get all edges in the graph.

        Returns:
            List of all edges
        """
        all_edges = []
        seen = set()

        for edges in self._edges.values():
            for edge in edges:
                edge_key = (edge.source_id, edge.target_id, edge.edge_type)
                if edge_key not in seen:
                    all_edges.append(edge)
                    seen.add(edge_key)

        return all_edges

    def node_count(self) -> int:
        """Get number of nodes."""
        return len(self._nodes)

    def edge_count(self) -> int:
        """Get number of edges."""
        return len(self.get_all_edges())

    def has_node(self, node_id: str) -> bool:
        """Check if node exists."""
        return node_id in self._nodes

    def has_edge(self, source_id: str, target_id: str, edge_type: str | None = None) -> bool:
        """Check if edge exists."""
        return self.get_edge(source_id, target_id, edge_type) is not None

    def query_nodes(self, filter_fn: Callable[[GraphNode], bool]) -> list[GraphNode]:
        """Query nodes using a filter function.

        Args:
            filter_fn: Function that takes a node and returns True if it matches

        Returns:
            List of matching nodes
        """
        return [node for node in self._nodes.values() if filter_fn(node)]

    def bfs(self, start_id: str, visit_fn: Callable[[GraphNode], None] | None = None) -> list[GraphNode]:
        """Breadth-first search traversal.

        Args:
            start_id: Starting node ID
            visit_fn: Optional function to call for each visited node

        Returns:
            List of nodes in BFS order
        """
        if start_id not in self._nodes:
            return []

        visited = set()
        queue = deque([start_id])
        result = []

        while queue:
            node_id = queue.popleft()
            if node_id in visited:
                continue

            visited.add(node_id)
            node = self._nodes[node_id]
            result.append(node)

            if visit_fn:
                visit_fn(node)

            # Add neighbors to queue
            for edge in self._edges.get(node_id, []):
                if edge.target_id not in visited:
                    queue.append(edge.target_id)

        return result

    def dfs(self, start_id: str, visit_fn: Callable[[GraphNode], None] | None = None) -> list[GraphNode]:
        """Depth-first search traversal.

        Args:
            start_id: Starting node ID
            visit_fn: Optional function to call for each visited node

        Returns:
            List of nodes in DFS order
        """
        if start_id not in self._nodes:
            return []

        visited = set()
        result = []

        def dfs_helper(node_id: str) -> None:
            if node_id in visited:
                return

            visited.add(node_id)
            node = self._nodes[node_id]
            result.append(node)

            if visit_fn:
                visit_fn(node)

            for edge in self._edges.get(node_id, []):
                dfs_helper(edge.target_id)

        dfs_helper(start_id)
        return result

    def find_path(self, start_id: str, end_id: str) -> list[GraphNode] | None:
        """Find a path between two nodes using BFS.

        Args:
            start_id: Starting node ID
            end_id: Target node ID

        Returns:
            List of nodes forming the path, or None if no path exists
        """
        if start_id not in self._nodes or end_id not in self._nodes:
            return None

        if start_id == end_id:
            return [self._nodes[start_id]]

        visited = set()
        queue = deque([(start_id, [start_id])])

        while queue:
            node_id, path = queue.popleft()

            if node_id in visited:
                continue

            visited.add(node_id)

            for edge in self._edges.get(node_id, []):
                if edge.target_id == end_id:
                    return [self._nodes[nid] for nid in path + [end_id]]

                if edge.target_id not in visited:
                    queue.append((edge.target_id, path + [edge.target_id]))

        return None

    def topological_sort(self) -> list[GraphNode]:
        """Perform topological sort on the graph.

        Returns:
            List of nodes in topological order

        Raises:
            ValueError: If graph contains cycles
        """
        if self.graph_type != GraphType.DIRECTED:
            raise ValueError("Topological sort only works on directed graphs")

        # Calculate in-degrees
        in_degree = {node_id: 0 for node_id in self._nodes}
        for edges in self._edges.values():
            for edge in edges:
                in_degree[edge.target_id] += 1

        # Find nodes with no incoming edges
        queue = deque([node_id for node_id, degree in in_degree.items() if degree == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(self._nodes[node_id])

            # Reduce in-degree for neighbors
            for edge in self._edges.get(node_id, []):
                in_degree[edge.target_id] -= 1
                if in_degree[edge.target_id] == 0:
                    queue.append(edge.target_id)

        # Check for cycles
        if len(result) != len(self._nodes):
            raise ValueError("Graph contains cycles, cannot perform topological sort")

        return result

    def detect_cycles(self) -> list[list[GraphNode]]:
        """Detect cycles in the graph.

        Returns:
            List of cycles, where each cycle is a list of nodes
        """
        if self.graph_type != GraphType.DIRECTED:
            return []

        visited = set()
        rec_stack = set()
        cycles = []

        def dfs_cycle(node_id: str, path: list[str]) -> None:
            visited.add(node_id)
            rec_stack.add(node_id)
            path.append(node_id)

            for edge in self._edges.get(node_id, []):
                target_id = edge.target_id

                if target_id not in visited:
                    dfs_cycle(target_id, path.copy())
                elif target_id in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(target_id)
                    cycle_nodes = [self._nodes[nid] for nid in path[cycle_start:]]
                    cycles.append(cycle_nodes)

            rec_stack.remove(node_id)

        for node_id in self._nodes:
            if node_id not in visited:
                dfs_cycle(node_id, [])

        return cycles

    def get_subgraph(self, node_ids: list[str]) -> Graph:
        """Extract a subgraph containing specified nodes.

        Args:
            node_ids: List of node IDs to include

        Returns:
            New graph containing only specified nodes and edges between them
        """
        subgraph = Graph(self.graph_type)

        # Add nodes
        for node_id in node_ids:
            if node_id in self._nodes:
                subgraph.add_node(self._nodes[node_id])

        # Add edges between included nodes
        for node_id in node_ids:
            if node_id in self._edges:
                for edge in self._edges[node_id]:
                    if edge.target_id in node_ids:
                        subgraph.add_edge(edge)

        return subgraph

    def to_dict(self) -> dict[str, Any]:
        """Convert graph to dictionary.

        Returns:
            Dictionary representation of the graph
        """
        return {
            "graph_type": self.graph_type.value,
            "nodes": [node.to_dict() for node in self._nodes.values()],
            "edges": [edge.to_dict() for edge in self.get_all_edges()]
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Graph:
        """Create graph from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            Graph instance
        """
        graph = cls(GraphType(data["graph_type"]))

        for node_data in data["nodes"]:
            graph.add_node(GraphNode.from_dict(node_data))

        for edge_data in data["edges"]:
            graph.add_edge(GraphEdge.from_dict(edge_data))

        return graph

    def save_json(self, file_path: str | Path) -> None:
        """Save graph to JSON file.

        Args:
            file_path: Path to save file
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_json(cls, file_path: str | Path) -> Graph:
        """Load graph from JSON file.

        Args:
            file_path: Path to load file

        Returns:
            Graph instance
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return cls.from_dict(data)

    def save_pickle(self, file_path: str | Path) -> None:
        """Save graph to pickle file.

        Args:
            file_path: Path to save file
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'wb') as f:
            pickle.dump(self, f)

    @classmethod
    def load_pickle(cls, file_path: str | Path) -> Graph:
        """Load graph from pickle file.

        Args:
            file_path: Path to load file

        Returns:
            Graph instance
        """
        with open(file_path, 'rb') as f:
            return pickle.load(f)

    def __repr__(self) -> str:
        """String representation."""
        return f"Graph(type={self.graph_type.value}, nodes={self.node_count()}, edges={self.edge_count()})"
