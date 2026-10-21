"""SQLite persistence and DAG operations."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class GraphError(Exception):
    def __init__(self, code, message, exit_code=4):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


SCHEMA = """
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    value REAL CHECK (value >= 0 AND value <= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE edges (
    parent_id INTEGER NOT NULL REFERENCES nodes(id),
    child_id INTEGER NOT NULL REFERENCES nodes(id),
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id),
    CHECK (parent_id <> child_id)
);
CREATE INDEX edges_by_child ON edges(child_id);
PRAGMA user_version = 1;
"""


class Graph:
    def __init__(self, path):
        # URI mode=rw never creates a database on a misspelled path.
        uri = Path(path).absolute().as_uri() + "?mode=rw"
        self.db = sqlite3.connect(uri, uri=True, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
            self.db.close()
            raise GraphError("invalid_database", "不是受支持的 rgraph 数据库。", 1)

    @staticmethod
    def initialize(path):
        target = Path(path)
        # Exclusive creation refuses to overwrite any existing file.
        with target.open("xb"):
            pass
        try:
            db = sqlite3.connect(target)
            try:
                db.executescript("BEGIN;\n" + SCHEMA + "\nCOMMIT;")
            finally:
                db.close()
        except Exception:
            target.unlink()
            raise
        return {"database": str(target), "schema_version": 1}

    def close(self):
        self.db.close()

    def begin(self, write=False):
        # Serialize validation and mutation; reads share one consistent snapshot.
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")

    def node(self, node_id):
        row = self.db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise GraphError("node_not_found", f"节点 {node_id} 不存在。", 3)
        return dict(row)

    def edge(self, parent, child):
        row = self.db.execute(
            "SELECT * FROM edges WHERE parent_id = ? AND child_id = ?", (parent, child)
        ).fetchone()
        if row is None:
            raise GraphError("edge_not_found", f"边 {parent} -> {child} 不存在。", 3)
        return dict(row)

    def descendants(self, node_id):
        # UNION (not UNION ALL) counts a shared descendant exactly once.
        return self.db.execute(
            """WITH RECURSIVE descendants(id) AS (
                SELECT child_id FROM edges WHERE parent_id = ?
                UNION
                SELECT e.child_id FROM edges e JOIN descendants d ON e.parent_id = d.id
            ) SELECT n.* FROM nodes n JOIN descendants d ON n.id = d.id""",
            (node_id,),
        ).fetchall()

    def summary(self, node_id):
        node = self.node(node_id)
        descendants = self.descendants(node_id)
        scored = [r["value"] for r in descendants if r["value"] is not None]
        node.update(
            subtree_value=sum(scored) / len(scored) if scored else None,
            descendant_count=len(descendants),
            scored_descendant_count=len(scored),
        )
        return node

    def show(self, node_id):
        node = self.summary(node_id)
        node["incoming"] = [dict(r) for r in self.db.execute(
            "SELECT * FROM edges WHERE child_id = ? ORDER BY parent_id", (node_id,))]
        node["outgoing"] = [dict(r) for r in self.db.execute(
            "SELECT * FROM edges WHERE parent_id = ? ORDER BY child_id", (node_id,))]
        return node

    def add(self, text, parent=None, edge_text=None):
        if parent is not None:
            self.node(parent)
        now = timestamp()
        cursor = self.db.execute(
            "INSERT INTO nodes(text, created_at, updated_at) VALUES (?, ?, ?)", (text, now, now)
        )
        node_id = cursor.lastrowid
        if parent is not None:
            self.link(parent, node_id, edge_text)
        return self.show(node_id)

    def link(self, parent, child, text):
        self.node(parent)
        self.node(child)
        if parent == child:
            raise GraphError("self_link", "节点不能连接到自身。")
        if self.db.execute("SELECT 1 FROM edges WHERE parent_id=? AND child_id=?", (parent, child)).fetchone():
            raise GraphError("edge_exists", f"边 {parent} -> {child} 已存在。")
        if any(r["id"] == parent for r in self.descendants(child)):
            raise GraphError("cycle_detected", f"连接 {parent} -> {child} 会形成环。")
        now = timestamp()
        self.db.execute(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?)", (parent, child, text, now, now)
        )
        return self.edge(parent, child)

    def update_text(self, text, node_id=None, parent=None, child=None, append=False):
        record = self.node(node_id) if node_id is not None else self.edge(parent, child)
        if append and record["text"]:
            text = record["text"] + "\n" + text
        if node_id is not None:
            self.db.execute("UPDATE nodes SET text=?, updated_at=? WHERE id=?", (text, timestamp(), node_id))
            return self.show(node_id)
        self.db.execute(
            "UPDATE edges SET text=?, updated_at=? WHERE parent_id=? AND child_id=?",
            (text, timestamp(), parent, child),
        )
        return self.edge(parent, child)

    def set_value(self, node_id, value):
        self.node(node_id)
        self.db.execute("UPDATE nodes SET value=?, updated_at=? WHERE id=?", (value, timestamp(), node_id))
        return self.show(node_id)

    def unlink(self, parent, child):
        self.edge(parent, child)
        self.db.execute("DELETE FROM edges WHERE parent_id=? AND child_id=?", (parent, child))
        return {"parent_id": parent, "child_id": child}

    def remove(self, node_id):
        self.node(node_id)
        if self.db.execute("SELECT 1 FROM edges WHERE parent_id=? OR child_id=?", (node_id, node_id)).fetchone():
            raise GraphError("node_connected", f"节点 {node_id} 仍有连接，请先 unlink。")
        self.db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        return {"id": node_id}

    def list_nodes(self, roots=False, unscored=False, sort="id", desc=False, limit=None):
        conditions = []
        if roots:
            conditions.append("NOT EXISTS (SELECT 1 FROM edges WHERE child_id=nodes.id)")
        if unscored:
            conditions.append("value IS NULL")
        query = "SELECT id FROM nodes" + (" WHERE " + " AND ".join(conditions) if conditions else "")
        nodes = [self.summary(r[0]) for r in self.db.execute(query + " ORDER BY id")]
        key = {"subtree-value": "subtree_value", "updated": "updated_at"}.get(sort, sort)
        present = [n for n in nodes if n[key] is not None]
        absent = [n for n in nodes if n[key] is None]
        present.sort(key=lambda n: n[key], reverse=desc)
        return (present + absent)[:limit]

    def search(self, query, scope):
        matches = []
        if scope in ("nodes", "all"):
            matches.extend({"type": "node", **dict(r)} for r in self.db.execute(
                "SELECT * FROM nodes WHERE instr(text, ?) > 0 ORDER BY id", (query,)))
        if scope in ("edges", "all"):
            matches.extend({"type": "edge", **dict(r)} for r in self.db.execute(
                "SELECT * FROM edges WHERE instr(text, ?) > 0 ORDER BY parent_id, child_id", (query,)))
        return matches

    def tree(self, node_id=None, depth=None):
        if node_id is not None:
            self.node(node_id)
            roots = [node_id]
        else:
            roots = [r[0] for r in self.db.execute(
                "SELECT id FROM nodes WHERE NOT EXISTS (SELECT 1 FROM edges WHERE child_id=nodes.id) ORDER BY id")]
        nodes, edges, seen = [], [], set()
        stack = [(n, 0) for n in reversed(roots)]
        while stack:
            current, level = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            nodes.append(self.summary(current))
            if depth is not None and level >= depth:
                continue
            outgoing = [dict(r) for r in self.db.execute(
                "SELECT * FROM edges WHERE parent_id=? ORDER BY child_id", (current,))]
            edges.extend(outgoing)
            stack.extend((e["child_id"], level + 1) for e in reversed(outgoing))
        return {"roots": roots, "nodes": nodes, "edges": edges}

    def export(self):
        return {
            "schema_version": 1,
            "nodes": [dict(r) for r in self.db.execute("SELECT * FROM nodes ORDER BY id")],
            "edges": [dict(r) for r in self.db.execute("SELECT * FROM edges ORDER BY parent_id, child_id")],
        }
