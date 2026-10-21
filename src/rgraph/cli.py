"""Command line interface for rgraph."""

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

from tortoise.exceptions import BaseORMException

from . import __version__
from .storage import Graph, GraphError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise GraphError("invalid_arguments", message, 2)


def nonnegative(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("必须为非负整数") from None
    if value < 0:
        raise argparse.ArgumentTypeError("必须为非负整数")
    return value


def coefficient(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("价值必须为 [0, 1] 内的有限数值") from None
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise argparse.ArgumentTypeError("价值必须为 [0, 1] 内的有限数值")
    return value


def text_options(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="直接提供文本")
    group.add_argument("--file", help="读取 UTF-8 文件；- 表示标准输入")


def parser():
    root = Parser(description="SQLite 文本研究 DAG")
    root.add_argument("--db", default="research.db", help="数据库路径，默认 research.db")
    root.add_argument("--json", action="store_true", help="输出 JSON")
    root.add_argument("--version", action="version", version=f"rgraph {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="初始化数据库")
    add = commands.add_parser("add", help="创建节点及可选父边")
    text_options(add)
    add.add_argument("--parent", type=int)
    add.add_argument("--edge-text")
    for name in ("edit", "append"):
        p = commands.add_parser(name, help="替换节点文本" if name == "edit" else "追加节点文本")
        p.add_argument("id", type=int)
        text_options(p)
    p = commands.add_parser("set-value", help="设置节点价值")
    p.add_argument("id", type=int)
    p.add_argument("value", type=coefficient)
    p = commands.add_parser("clear-value", help="清除节点价值")
    p.add_argument("id", type=int)
    p = commands.add_parser("show", help="查看节点及相邻边")
    p.add_argument("id", type=int)
    p.add_argument("--text-only", action="store_true")
    p = commands.add_parser("list", help="列出节点")
    p.add_argument("--roots", action="store_true")
    p.add_argument("--unscored", action="store_true")
    p.add_argument("--sort", choices=("id", "value", "subtree-value", "updated"), default="id")
    p.add_argument("--desc", action="store_true")
    p.add_argument("--limit", type=nonnegative)
    p = commands.add_parser("search", help="字面子串搜索，区分大小写")
    p.add_argument("query")
    p.add_argument("--in", dest="scope", choices=("nodes", "edges", "all"), default="all")
    p = commands.add_parser("tree", help="查看后续图结构")
    p.add_argument("id", type=int, nargs="?")
    p.add_argument("--depth", type=nonnegative)
    for name in ("link", "unlink"):
        p = commands.add_parser(name, help="连接节点" if name == "link" else "移除边")
        p.add_argument("parent", type=int)
        p.add_argument("child", type=int)
        if name == "link":
            text_options(p)
    p = commands.add_parser("edge", help="查看或修改边文本")
    sub = p.add_subparsers(dest="edge_command", required=True)
    for name in ("show", "edit", "append"):
        p = sub.add_parser(name)
        p.add_argument("parent", type=int)
        p.add_argument("child", type=int)
        if name != "show":
            text_options(p)
    p = commands.add_parser("rm", help="删除没有连接的节点")
    p.add_argument("id", type=int)
    commands.add_parser("export", help="以 JSON 导出整个图")
    return root


def read_text(args):
    if args.text is not None:
        return args.text
    if args.file == "-":
        return sys.stdin.read()
    with Path(args.file).open(encoding="utf-8", newline="") as stream:
        return stream.read()


async def execute(graph, args):
    command = args.command
    if command == "add":
        return await graph.add(read_text(args), args.parent, args.edge_text)
    if command in ("edit", "append"):
        return await graph.update_text(read_text(args), node_id=args.id, append=command == "append")
    if command in ("set-value", "clear-value"):
        return await graph.set_value(args.id, args.value if command == "set-value" else None)
    if command == "show":
        return await graph.show(args.id)
    if command == "list":
        return await graph.list_nodes(args.roots, args.unscored, args.sort, args.desc, args.limit)
    if command == "search":
        return await graph.search(args.query, args.scope)
    if command == "tree":
        return await graph.tree(args.id, args.depth)
    if command == "link":
        return await graph.link(args.parent, args.child, read_text(args))
    if command == "unlink":
        return await graph.unlink(args.parent, args.child)
    if command == "edge":
        if args.edge_command == "show":
            return await graph.edge(args.parent, args.child)
        return await graph.update_text(read_text(args), parent=args.parent, child=args.child,
                                 append=args.edge_command == "append")
    if command == "rm":
        return await graph.remove(args.id)
    if command == "export":
        return await graph.export()
    raise AssertionError(command)


def number(value):
    return "—" if value is None else f"{value:.6g}"


def preview(text):
    line = next((s.strip() for s in text.splitlines() if s.strip()), "")
    return line if len(line) <= 60 else line[:59] + "…"


def render_tree(data, depth):
    nodes = {n["id"]: n for n in data["nodes"]}
    outgoing = {}
    for edge in data["edges"]:
        outgoing.setdefault(edge["parent_id"], []).append(edge)
    seen = set()
    stack = [(root, "", "", 0, None) for root in reversed(data["roots"])]
    while stack:
        node_id, prefix, connector, level, edge = stack.pop()
        if edge is not None:
            lines = edge["text"].splitlines() or [""]
            print(prefix + connector + lines[0])
            continuation = "    " if connector == "└── " else "│   "
            for line in lines[1:]:
                print(prefix + continuation + line)
            prefix += continuation
            connector = "└── "
        if node_id in seen:
            print(f"{prefix}{connector}[{node_id}] ↩")
            continue
        seen.add(node_id)
        node = nodes[node_id]
        print(f"{prefix}{connector}[{node_id}] {preview(node['text'])}  "
              f"value={number(node['value'])}  subtree={number(node['subtree_value'])}")
        if depth is not None and level >= depth:
            continue
        child_prefix = prefix + ("    " if connector == "└── " else "│   " if connector else "")
        children = outgoing.get(node_id, [])
        for index in range(len(children) - 1, -1, -1):
            edge = children[index]
            stack.append((edge["child_id"], child_prefix,
                          "└── " if index == len(children) - 1 else "├── ", level + 1, edge))


def render(result, args):
    command = args.command
    if args.json or command == "export":
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    elif command == "init":
        print(f"Initialized {result['database']}")
    elif command == "add":
        print(result["id"])
    elif command == "show":
        if args.text_only:
            sys.stdout.write(result["text"])
            return
        print(f"ID:                 {result['id']}")
        print(f"Value:              {number(result['value'])}")
        print(f"Subtree value:      {number(result['subtree_value'])}")
        print(f"Descendants scored: {result['scored_descendant_count']} / {result['descendant_count']}")
        print(f"Created:            {result['created_at']}")
        print(f"Updated:            {result['updated_at']}")
        print("\nText:\n" + result["text"])
        for label, key in (("Incoming", "incoming"), ("Outgoing", "outgoing")):
            print(f"\n{label}:")
            for edge in result[key]:
                print(f"{edge['parent_id']} -> {edge['child_id']}\n{edge['text']}")
    elif command == "list":
        print("ID\tVALUE\tSUBTREE\tSCORED/TOTAL\tTEXT")
        for node in result:
            print(f"{node['id']}\t{number(node['value'])}\t{number(node['subtree_value'])}\t"
                  f"{node['scored_descendant_count']}/{node['descendant_count']}\t{preview(node['text'])}")
    elif command == "search":
        for match in result:
            label = str(match["id"]) if match["type"] == "node" else f"{match['parent_id']} -> {match['child_id']}"
            print(f"{match['type']} {label}\n{match['text']}\n")
    elif command == "tree":
        render_tree(result, args.depth)
    elif command == "edge" and args.edge_command == "show":
        print(f"{result['parent_id']} -> {result['child_id']}")
        print(f"Created: {result['created_at']}\nUpdated: {result['updated_at']}\n\n{result['text']}")
    elif "parent_id" in result:
        print(f"OK {result['parent_id']} -> {result['child_id']}")
    else:
        print(f"OK {result['id']}")


def normalize_globals(argv):
    """Accept --db and --json before or after subcommands, preserving text arguments."""
    leading, trailing = [], []
    # Skip values belonging to text options even when they resemble global flags.
    value_options = {"--text", "--file", "--edge-text", "--parent", "--sort", "--limit", "--depth", "--in"}
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            trailing.extend(argv[i:])
            break
        if token == "--json" or token.startswith("--db="):
            leading.append(token)
        elif token == "--db":
            leading.append(token)
            if i + 1 < len(argv):
                i += 1
                leading.append(argv[i])
        elif token in value_options:
            trailing.append(token)
            if i + 1 < len(argv):
                i += 1
                trailing.append(argv[i])
        else:
            trailing.append(token)
        i += 1
    return leading + trailing, "--json" in leading


async def run_command(args):
    if args.command == "init":
        return await Graph.initialize(args.db)
    graph = await Graph.open(args.db)
    try:
        write = args.command in {"add", "edit", "append", "set-value", "clear-value", "link", "unlink", "rm"} or (
            args.command == "edge" and args.edge_command != "show")
        async with graph.transaction(write):
            return await execute(graph, args)
    finally:
        await graph.close()


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    normalized, json_mode = normalize_globals(raw)
    # Parsing failures also use JSON when a real global --json was supplied.
    try:
        args = parser().parse_args(normalized)
        json_mode = args.json
        if args.command == "add" and ((args.parent is None) != (args.edge_text is None)):
            raise GraphError("invalid_arguments", "--parent 和 --edge-text 必须一起使用。", 2)
        if args.command == "show" and args.text_only and args.json:
            raise GraphError("invalid_arguments", "--text-only 不能与 --json 同时使用。", 2)
        result = asyncio.run(run_command(args))
        render(result, args)
        return 0
    except (GraphError, OSError, BaseORMException, UnicodeError) as exc:
        if isinstance(exc, GraphError):
            code, status = exc.code, exc.exit_code
        elif isinstance(exc, FileExistsError):
            code, status = "database_exists", 4
        else:
            code, status = "execution_error", 1
        error = {"error": {"code": code, "message": str(exc)}}
        print(json.dumps(error, ensure_ascii=False) if json_mode else f"Error [{code}]: {exc}", file=sys.stderr)
        return status


if __name__ == "__main__":
    sys.exit(main())
