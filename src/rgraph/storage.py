"""Tortoise ORM persistence and DAG operations."""

from contextlib import asynccontextmanager

from tortoise import Tortoise, connections
from tortoise.expressions import F, Q
from tortoise.transactions import in_transaction

from .models import Edge, Node
from datetime import datetime, timezone
from pathlib import Path


class GraphError(Exception):
    def __init__(self, code, message, exit_code=4):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


NODE_FIELDS = ("id", "text", "conclusion", "code_dir", "value", "created_at", "updated_at")
EDGE_FIELDS = ("parent_id", "child_id", "observation", "action", "created_at", "updated_at")
SCHEMA_VERSION = 4


class Graph:
    @staticmethod
    async def connect(path):
        await Tortoise.init(config={
            "connections": {"default": {
                "engine": "tortoise.backends.sqlite",
                "credentials": {"file_path": str(Path(path).absolute()),
                                "journal_mode": "DELETE", "busy_timeout": 5000},
            }},
            "apps": {"models": {"models": ["rgraph.models"], "default_connection": "default"}},
        })

    @classmethod
    async def open(cls, path):
        # Refuse missing paths before the ORM can create a database.
        with Path(path).open("rb"):
            pass
        await cls.connect(path)
        try:
            db = connections.get("default")
            rows = await db.execute_query_dict("PRAGMA user_version")
            if rows[0]["user_version"] != SCHEMA_VERSION:
                raise GraphError("invalid_database", "不是版本 4 的 rgraph 数据库，请使用新数据库。", 1)
            return cls()
        except BaseException:
            await Tortoise.close_connections()
            raise

    @classmethod
    async def initialize(cls, path):
        target = Path(path)
        with target.open("xb"):
            pass
        try:
            await cls.connect(path)
            await Tortoise.generate_schemas(safe=False)
            db = connections.get("default")
            await db.execute_script("""
                CREATE TRIGGER nodes_value_insert BEFORE INSERT ON nodes
                WHEN NEW.value < 0 OR NEW.value > 1
                BEGIN SELECT RAISE(ABORT, 'value out of range'); END;
                CREATE TRIGGER nodes_value_update BEFORE UPDATE OF value ON nodes
                WHEN NEW.value < 0 OR NEW.value > 1
                BEGIN SELECT RAISE(ABORT, 'value out of range'); END;
                CREATE TRIGGER edges_self_insert BEFORE INSERT ON edges
                WHEN NEW.parent_id = NEW.child_id
                BEGIN SELECT RAISE(ABORT, 'self link'); END;
                CREATE TRIGGER edges_self_update BEFORE UPDATE OF parent_id, child_id ON edges
                WHEN NEW.parent_id = NEW.child_id
                BEGIN SELECT RAISE(ABORT, 'self link'); END;
                PRAGMA user_version = 4;
            """)
        except BaseException:
            await Tortoise.close_connections()
            target.unlink()
            raise
        else:
            await Tortoise.close_connections()
        return {"database": str(target), "schema_version": SCHEMA_VERSION}

    async def close(self):
        await Tortoise.close_connections()

    @asynccontextmanager
    async def transaction(self, write=False):
        async with in_transaction() as db:
            if write:
                # Acquire SQLite's write reservation before graph validation.
                await Node.filter(id=-1).using_db(db).update(text=F("text"))
            yield

    async def node(self, node_id):
        row = await Node.filter(id=node_id).values(*NODE_FIELDS)
        if not row:
            raise GraphError("node_not_found", f"节点 {node_id} 不存在。", 3)
        return row[0]

    async def edge(self, parent, child):
        rows = await Edge.filter(parent_id=parent, child_id=child).values(*EDGE_FIELDS)
        if not rows:
            raise GraphError("edge_not_found", f"边 {parent} -> {child} 不存在。", 3)
        return rows[0]

    async def descendants(self, node_id):
        seen, frontier = set(), {node_id}
        while frontier:
            children = set(await Edge.filter(parent_id__in=frontier).values_list("child_id", flat=True))
            frontier = children - seen
            seen.update(frontier)
        return await Node.filter(id__in=seen).values(*NODE_FIELDS)

    async def summary(self, node_id):
        node = await self.node(node_id)
        descendants = await self.descendants(node_id)
        scored = [r["value"] for r in descendants if r["value"] is not None]
        node.update(subtree_value=sum(scored) / len(scored) if scored else None,
                    descendant_count=len(descendants), scored_descendant_count=len(scored))
        return node

    async def show(self, node_id):
        node = await self.summary(node_id)
        node["incoming"] = await Edge.filter(child_id=node_id).order_by("parent_id").values(*EDGE_FIELDS)
        node["outgoing"] = await Edge.filter(parent_id=node_id).order_by("child_id").values(*EDGE_FIELDS)
        return node

    async def add(self, text, parent=None, observation=None, action=None, conclusion=None, code_dir=None):
        if conclusion is not None:
            self.validate_conclusion(conclusion)
        if code_dir is not None:
            code_dir = self.validate_code_dir(code_dir)
        if parent is None:
            if await Node.exists():
                raise GraphError("parent_required", "已有研究节点，后续节点必须通过 --parent 从已有节点创建。")
        else:
            await self.require_expandable(parent)
        now = timestamp()
        node = await Node.create(text=text, conclusion=conclusion, code_dir=code_dir, created_at=now, updated_at=now)
        if parent is not None:
            await self.link(parent, node.id, observation, action)
        return await self.show(node.id)

    async def require_expandable(self, node_id):
        node = await self.node(node_id)
        missing = []
        if not node["conclusion"] or not node["conclusion"].strip():
            missing.append("结论（set-conclusion）")
        if not node["code_dir"]:
            missing.append("实验代码目录（set-code-dir）")
        if missing:
            raise GraphError("node_incomplete", f"节点 {node_id} 缺少{'、'.join(missing)}，补全后才能创建后续节点或连接。")
        self.validate_code_dir(node["code_dir"])

    async def link(self, parent, child, observation, action):
        self.validate_edge_fields(observation, action)
        await self.require_expandable(parent)
        await self.node(child)
        if parent == child:
            raise GraphError("self_link", "节点不能连接到自身。")
        if await Edge.filter(parent_id=parent, child_id=child).exists():
            raise GraphError("edge_exists", f"边 {parent} -> {child} 已存在。")
        if any(r["id"] == parent for r in await self.descendants(child)):
            raise GraphError("cycle_detected", f"连接 {parent} -> {child} 会形成环。")
        now = timestamp()
        await Edge.create(parent_id=parent, child_id=child, observation=observation, action=action, created_at=now, updated_at=now)
        return await self.edge(parent, child)

    @staticmethod
    def validate_edge_fields(observation=None, action=None):
        for name, value in (("observation", observation), ("action", action)):
            if value is not None and not value.strip():
                raise GraphError("invalid_arguments", f"{name} 不可为空或仅含空白。", 2)

    async def update_text(self, text, node_id, append=False):
        record = await self.node(node_id)
        if append and record["text"]:
            text = record["text"] + "\n" + text
        await Node.filter(id=node_id).update(text=text, updated_at=timestamp())
        return await self.show(node_id)

    async def update_edge(self, parent, child, observation=None, action=None, append=False):
        self.validate_edge_fields(observation, action)
        record = await self.edge(parent, child)
        changes = {}
        for name, value in (("observation", observation), ("action", action)):
            if value is not None:
                changes[name] = record[name] + "\n" + value if append else value
        if not changes:
            raise GraphError("invalid_arguments", "至少指定 --observation 或 --action。", 2)
        await Edge.filter(parent_id=parent, child_id=child).update(**changes, updated_at=timestamp())
        return await self.edge(parent, child)

    @staticmethod
    def validate_conclusion(conclusion):
        if not conclusion.strip():
            raise GraphError("invalid_arguments", "结论不可为空或仅含空白。", 2)

    @staticmethod
    def validate_code_dir(code_dir):
        if not code_dir.strip():
            raise GraphError("invalid_arguments", "实验代码目录不可为空。", 2)
        directory = Path(code_dir).expanduser().resolve()
        if not directory.is_dir():
            raise GraphError("invalid_code_dir", f"实验代码目录不存在或不是目录：{directory}", 2)
        readmes = [entry for entry in directory.iterdir()
                   if entry.is_file() and (entry.name.lower() == "readme"
                                          or entry.name.lower().startswith("readme."))]
        if not readmes:
            raise GraphError("readme_required",
                             f"实验代码目录 {directory} 下缺少 README。请在目录根部补全复现实验的 README（例如 README.md），说明环境、运行步骤及结果复现方式后再设置。", 2)
        return str(directory)

    async def set_conclusion(self, node_id, conclusion):
        await self.node(node_id)
        self.validate_conclusion(conclusion)
        await Node.filter(id=node_id).update(conclusion=conclusion, updated_at=timestamp())
        return await self.show(node_id)

    async def set_code_dir(self, node_id, code_dir):
        await self.node(node_id)
        directory = self.validate_code_dir(code_dir)
        await Node.filter(id=node_id).update(code_dir=directory, updated_at=timestamp())
        return await self.show(node_id)

    async def set_value(self, node_id, value):
        await self.node(node_id)
        await Node.filter(id=node_id).update(value=value, updated_at=timestamp())
        return await self.show(node_id)

    async def unlink(self, parent, child):
        await self.edge(parent, child)
        await Edge.filter(parent_id=parent, child_id=child).delete()
        return {"parent_id": parent, "child_id": child}

    async def remove(self, node_id):
        await self.node(node_id)
        if await Edge.filter(Q(parent_id=node_id) | Q(child_id=node_id)).exists():
            raise GraphError("node_connected", f"节点 {node_id} 仍有连接，请先 unlink。")
        await Node.filter(id=node_id).delete()
        return {"id": node_id}

    async def root_ids(self):
        children = await Edge.all().values_list("child_id", flat=True)
        return await Node.exclude(id__in=children).order_by("id").values_list("id", flat=True)

    async def list_nodes(self, roots=False, unscored=False, sort="id", desc=False, limit=None):
        query = Node.all()
        if roots:
            query = query.filter(id__in=await self.root_ids())
        if unscored:
            query = query.filter(value__isnull=True)
        ids = await query.order_by("id").values_list("id", flat=True)
        nodes = [await self.summary(node_id) for node_id in ids]
        key = {"subtree-value": "subtree_value", "updated": "updated_at"}.get(sort, sort)
        present = [n for n in nodes if n[key] is not None]
        absent = [n for n in nodes if n[key] is None]
        present.sort(key=lambda n: n[key], reverse=desc)
        return (present + absent)[:limit]

    async def search(self, query, scope):
        matches = []
        # Python substring matching preserves case and literal %, _ and NUL.
        if scope in ("nodes", "all"):
            rows = await Node.all().order_by("id").values(*NODE_FIELDS)
            matches.extend({"type": "node", **r} for r in rows if query in r["text"] or query in (r["conclusion"] or ""))
        if scope in ("edges", "all"):
            rows = await Edge.all().order_by("parent_id", "child_id").values(*EDGE_FIELDS)
            matches.extend({"type": "edge", **r} for r in rows if query in r["observation"] or query in r["action"])
        return matches

    async def tree(self, node_id=None, depth=None):
        if node_id is not None:
            await self.node(node_id)
            roots = [node_id]
        else:
            roots = await self.root_ids()
        nodes, edges, seen = [], [], set()
        stack = [(n, 0) for n in reversed(roots)]
        while stack:
            current, level = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            nodes.append(await self.summary(current))
            if depth is not None and level >= depth:
                continue
            outgoing = await Edge.filter(parent_id=current).order_by("child_id").values(*EDGE_FIELDS)
            edges.extend(outgoing)
            stack.extend((e["child_id"], level + 1) for e in reversed(outgoing))
        return {"roots": roots, "nodes": nodes, "edges": edges}

    async def export(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "nodes": await Node.all().order_by("id").values(*NODE_FIELDS),
            "edges": await Edge.all().order_by("parent_id", "child_id").values(*EDGE_FIELDS),
        }
