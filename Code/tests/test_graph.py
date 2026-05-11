"""Unit tests for graph data structure."""

import pytest
from pathlib import Path
import tempfile
import json

from core.graph import Graph, GraphNode, GraphEdge, GraphType


class TestGraphNode:
    """Tests for GraphNode class."""

    def test_create_node(self):
        """Test node creation."""
        node = GraphNode(
            id="node1",
            type="test",
            data={"value": 42},
            metadata={"tag": "important"}
        )
        assert node.id == "node1"
        assert node.type == "test"
        assert node.data["value"] == 42
        assert node.metadata["tag"] == "important"
        assert node.created_at is not None
        assert node.updated_at is not None

    def test_node_to_dict(self):
        """Test node serialization to dict."""
        node = GraphNode(id="node1", type="test", data={"value": 42})
        node_dict = node.to_dict()
        assert node_dict["id"] == "node1"
        assert node_dict["type"] == "test"
        assert node_dict["data"]["value"] == 42

    def test_node_from_dict(self):
        """Test node deserialization from dict."""
        node_dict = {
            "id": "node1",
            "type": "test",
            "data": {"value": 42},
            "metadata": {},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z"
        }
        node = GraphNode.from_dict(node_dict)
        assert node.id == "node1"
        assert node.type == "test"
        assert node.data["value"] == 42

    def test_node_update(self):
        """Test node update."""
        node = GraphNode(id="node1", type="test", data={"value": 42})
        original_updated_at = node.updated_at

        node.update(data={"value": 100}, metadata={"new": "meta"})

        assert node.data["value"] == 100
        assert node.metadata["new"] == "meta"
        assert node.updated_at != original_updated_at


class TestGraphEdge:
    """Tests for GraphEdge class."""

    def test_create_edge(self):
        """Test edge creation."""
        edge = GraphEdge(
            source_id="node1",
            target_id="node2",
            edge_type="connects",
            weight=0.8
        )
        assert edge.source_id == "node1"
        assert edge.target_id == "node2"
        assert edge.edge_type == "connects"
        assert edge.weight == 0.8

    def test_edge_reverse(self):
        """Test edge reversal."""
        edge = GraphEdge(source_id="node1", target_id="node2", edge_type="connects")
        reversed_edge = edge.reverse()
        assert reversed_edge.source_id == "node2"
        assert reversed_edge.target_id == "node1"
        assert reversed_edge.edge_type == "connects"


class TestGraph:
    """Tests for Graph class."""

    def test_create_directed_graph(self):
        """Test directed graph creation."""
        graph = Graph(GraphType.DIRECTED)
        assert graph.graph_type == GraphType.DIRECTED
        assert graph.node_count() == 0
        assert graph.edge_count() == 0

    def test_create_undirected_graph(self):
        """Test undirected graph creation."""
        graph = Graph(GraphType.UNDIRECTED)
        assert graph.graph_type == GraphType.UNDIRECTED

    def test_add_node(self):
        """Test adding nodes."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")

        graph.add_node(node1)
        graph.add_node(node2)

        assert graph.node_count() == 2
        assert graph.has_node("node1")
        assert graph.has_node("node2")

    def test_add_edge(self):
        """Test adding edges."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")

        graph.add_node(node1)
        graph.add_node(node2)

        edge = GraphEdge(source_id="node1", target_id="node2")
        graph.add_edge(edge)

        assert graph.edge_count() == 1
        assert graph.has_edge("node1", "node2")

    def test_add_edge_nonexistent_node(self):
        """Test adding edge with nonexistent nodes."""
        graph = Graph()
        edge = GraphEdge(source_id="node1", target_id="node2")

        with pytest.raises(ValueError):
            graph.add_edge(edge)

    def test_get_node(self):
        """Test getting nodes."""
        graph = Graph()
        node = GraphNode(id="node1", type="test", data={"value": 42})
        graph.add_node(node)

        retrieved = graph.get_node("node1")
        assert retrieved is not None
        assert retrieved.id == "node1"
        assert retrieved.data["value"] == 42

        assert graph.get_node("nonexistent") is None

    def test_get_edge(self):
        """Test getting edges."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")
        graph.add_node(node1)
        graph.add_node(node2)

        edge = GraphEdge(source_id="node1", target_id="node2", edge_type="connects")
        graph.add_edge(edge)

        retrieved = graph.get_edge("node1", "node2")
        assert retrieved is not None
        assert retrieved.edge_type == "connects"

    def test_remove_node(self):
        """Test removing nodes."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")
        graph.add_node(node1)
        graph.add_node(node2)

        edge = GraphEdge(source_id="node1", target_id="node2")
        graph.add_edge(edge)

        assert graph.remove_node("node1")
        assert graph.node_count() == 1
        assert not graph.has_node("node1")
        assert graph.edge_count() == 0  # Edge should be removed too

    def test_remove_edge(self):
        """Test removing edges."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")
        graph.add_node(node1)
        graph.add_node(node2)

        edge = GraphEdge(source_id="node1", target_id="node2")
        graph.add_edge(edge)

        assert graph.remove_edge("node1", "node2")
        assert graph.edge_count() == 0
        assert not graph.has_edge("node1", "node2")

    def test_get_neighbors(self):
        """Test getting neighbors."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")
        node3 = GraphNode(id="node3", type="test")

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)

        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node1", target_id="node3"))

        neighbors = graph.get_neighbors("node1")
        assert len(neighbors) == 2
        neighbor_ids = {n.id for n in neighbors}
        assert neighbor_ids == {"node2", "node3"}

    def test_get_predecessors(self):
        """Test getting predecessors."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")
        node3 = GraphNode(id="node3", type="test")

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)

        graph.add_edge(GraphEdge(source_id="node1", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node3"))

        predecessors = graph.get_predecessors("node3")
        assert len(predecessors) == 2
        pred_ids = {n.id for n in predecessors}
        assert pred_ids == {"node1", "node2"}

    def test_query_nodes(self):
        """Test querying nodes."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="type_a", data={"value": 10})
        node2 = GraphNode(id="node2", type="type_b", data={"value": 20})
        node3 = GraphNode(id="node3", type="type_a", data={"value": 30})

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_node(node3)

        # Query by type
        type_a_nodes = graph.query_nodes(lambda n: n.type == "type_a")
        assert len(type_a_nodes) == 2

        # Query by data value
        high_value_nodes = graph.query_nodes(lambda n: n.data.get("value", 0) > 15)
        assert len(high_value_nodes) == 2

    def test_bfs(self):
        """Test breadth-first search."""
        graph = Graph()
        for i in range(1, 6):
            graph.add_node(GraphNode(id=f"node{i}", type="test"))

        # Create a tree structure
        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node1", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node4"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node5"))

        result = graph.bfs("node1")
        assert len(result) == 5
        assert result[0].id == "node1"

    def test_dfs(self):
        """Test depth-first search."""
        graph = Graph()
        for i in range(1, 6):
            graph.add_node(GraphNode(id=f"node{i}", type="test"))

        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node1", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node4"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node5"))

        result = graph.dfs("node1")
        assert len(result) == 5
        assert result[0].id == "node1"

    def test_find_path(self):
        """Test finding path between nodes."""
        graph = Graph()
        for i in range(1, 5):
            graph.add_node(GraphNode(id=f"node{i}", type="test"))

        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node3", target_id="node4"))

        path = graph.find_path("node1", "node4")
        assert path is not None
        assert len(path) == 4
        assert [n.id for n in path] == ["node1", "node2", "node3", "node4"]

        # No path exists
        graph.add_node(GraphNode(id="node5", type="test"))
        path = graph.find_path("node1", "node5")
        assert path is None

    def test_topological_sort(self):
        """Test topological sort."""
        graph = Graph(GraphType.DIRECTED)
        for i in range(1, 6):
            graph.add_node(GraphNode(id=f"task{i}", type="task"))

        # Create dependencies
        graph.add_edge(GraphEdge(source_id="task1", target_id="task2"))
        graph.add_edge(GraphEdge(source_id="task1", target_id="task3"))
        graph.add_edge(GraphEdge(source_id="task2", target_id="task4"))
        graph.add_edge(GraphEdge(source_id="task3", target_id="task4"))
        graph.add_edge(GraphEdge(source_id="task4", target_id="task5"))

        sorted_nodes = graph.topological_sort()
        assert len(sorted_nodes) == 5
        assert sorted_nodes[0].id == "task1"
        assert sorted_nodes[-1].id == "task5"

    def test_topological_sort_with_cycle(self):
        """Test topological sort with cycle."""
        graph = Graph(GraphType.DIRECTED)
        graph.add_node(GraphNode(id="node1", type="test"))
        graph.add_node(GraphNode(id="node2", type="test"))
        graph.add_node(GraphNode(id="node3", type="test"))

        # Create a cycle
        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node3", target_id="node1"))

        with pytest.raises(ValueError, match="contains cycles"):
            graph.topological_sort()

    def test_detect_cycles(self):
        """Test cycle detection."""
        graph = Graph(GraphType.DIRECTED)
        graph.add_node(GraphNode(id="node1", type="test"))
        graph.add_node(GraphNode(id="node2", type="test"))
        graph.add_node(GraphNode(id="node3", type="test"))

        # No cycles initially
        cycles = graph.detect_cycles()
        assert len(cycles) == 0

        # Create a cycle
        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node3", target_id="node1"))

        cycles = graph.detect_cycles()
        assert len(cycles) > 0

    def test_get_subgraph(self):
        """Test subgraph extraction."""
        graph = Graph()
        for i in range(1, 6):
            graph.add_node(GraphNode(id=f"node{i}", type="test"))

        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))
        graph.add_edge(GraphEdge(source_id="node2", target_id="node3"))
        graph.add_edge(GraphEdge(source_id="node3", target_id="node4"))
        graph.add_edge(GraphEdge(source_id="node4", target_id="node5"))

        subgraph = graph.get_subgraph(["node1", "node2", "node3"])
        assert subgraph.node_count() == 3
        assert subgraph.edge_count() == 2

    def test_undirected_graph_edges(self):
        """Test undirected graph edge behavior."""
        graph = Graph(GraphType.UNDIRECTED)
        node1 = GraphNode(id="node1", type="test")
        node2 = GraphNode(id="node2", type="test")

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))

        # In undirected graph, edge exists in both directions
        assert graph.has_edge("node1", "node2")
        assert graph.has_edge("node2", "node1")

    def test_serialization_json(self):
        """Test JSON serialization."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test", data={"value": 42})
        node2 = GraphNode(id="node2", type="test", data={"value": 100})

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "graph.json"
            graph.save_json(file_path)

            loaded_graph = Graph.load_json(file_path)
            assert loaded_graph.node_count() == 2
            assert loaded_graph.edge_count() == 1
            assert loaded_graph.get_node("node1").data["value"] == 42

    def test_serialization_pickle(self):
        """Test pickle serialization."""
        graph = Graph()
        node1 = GraphNode(id="node1", type="test", data={"value": 42})
        node2 = GraphNode(id="node2", type="test", data={"value": 100})

        graph.add_node(node1)
        graph.add_node(node2)
        graph.add_edge(GraphEdge(source_id="node1", target_id="node2"))

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "graph.pkl"
            graph.save_pickle(file_path)

            loaded_graph = Graph.load_pickle(file_path)
            assert loaded_graph.node_count() == 2
            assert loaded_graph.edge_count() == 1
