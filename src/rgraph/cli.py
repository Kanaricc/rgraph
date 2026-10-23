"""Command line interface for rgraph."""

import argparse
import asyncio
import json
import math
import shutil
import sys
import unicodedata
from pathlib import Path

from tortoise.exceptions import BaseORMException

from . import __version__
from .helptext import COMMANDS, EDGE_COMMANDS, GLOBAL_NOTE, OVERVIEW
from .storage import Graph, GraphError


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)

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


def edge_options(parser, required=False):
    parser.add_argument("--observation", required=required, help="导致改进的观测原因，不可为空")
    parser.add_argument("--action", required=required, help="下一步要做什么，不可为空")


def edge_text(edge):
    return f"Observation: {edge['observation']}\nAction: {edge['action']}"


def parser():
    root = Parser(prog="rgraph", description="管理研究 DAG：文本节点、实验结论与代码目录，以及观测/动作边。", epilog=OVERVIEW)
    root.add_argument("--db", default="research.db", help="数据库路径，默认 research.db")
    root.add_argument("--json", action="store_true", help="输出 JSON")
    root.add_argument("--version", action="version", version=f"rgraph {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="初始化数据库")
    add = commands.add_parser("add", help="创建节点及可选父边")
    text_options(add)
    add.add_argument("--parent", type=int, help="已有父节点 ID；非空图必填，父节点须补齐结论和实验目录")
    edge_options(add)
    add.add_argument("--conclusion", help="仅在实验结束后填写具体结论，禁止占位信息；可后续设置")
    add.add_argument("--code-dir", help="实验代码目录，根部必须有 README")
    for name in ("edit", "append"):
        p = commands.add_parser(name, help="替换节点文本" if name == "edit" else "追加节点文本")
        p.add_argument("id", type=int, help="已有节点的整数 ID")
        text_options(p)
    p = commands.add_parser("set-conclusion", help="设置节点结论")
    p.add_argument("id", type=int, help="已有节点的整数 ID")
    text_options(p)
    p = commands.add_parser("set-code-dir", help="设置实验代码目录并检查复现 README")
    p.add_argument("id", type=int, help="已有节点的整数 ID")
    p.add_argument("path", help="实验代码目录")
    p = commands.add_parser("set-value", help="设置节点价值")
    p.add_argument("id", type=int, help="已有节点的整数 ID")
    p.add_argument("value", type=coefficient, help="人工价值系数：[0,1] 内的有限数")
    p = commands.add_parser("clear-value", help="清除节点价值")
    p.add_argument("id", type=int, help="已有节点的整数 ID")
    p = commands.add_parser("show", help="查看节点及相邻边")
    p.add_argument("id", type=int, help="已有节点的整数 ID")
    p.add_argument("--text-only", action="store_true", help="仅输出原始 text，无附加换行；与 --json 互斥")
    p = commands.add_parser("list", help="列出节点")
    p.add_argument("--roots", action="store_true", help="仅列出没有入边的节点")
    p.add_argument("--unscored", action="store_true", help="仅列出 value 为 null 的未评估节点")
    p.add_argument("--sort", choices=("id", "value", "subtree-value", "updated"), default="id", help="排序依据，默认 id；空价值始终排最后")
    p.add_argument("--desc", action="store_true", help="按所选依据降序排列")
    p.add_argument("--limit", type=nonnegative, help="最多返回多少节点；非负整数，默认全部")
    p = commands.add_parser("search", help="字面子串搜索，区分大小写")
    p.add_argument("query", help="区分大小写的字面子串")
    p.add_argument("--in", dest="scope", choices=("nodes", "edges", "all"), default="all", help="搜索范围，默认 all")
    p = commands.add_parser("tree", help="查看后续图结构")
    p.add_argument("id", type=int, nargs="?", help="展开起点 ID；省略则从所有根节点开始")
    p.add_argument("--depth", type=nonnegative, help="最大边数深度；0 仅起点，默认无限制")
    p.add_argument("--full", action="store_true", help="展开节点文本、结论、观察和行动全文")
    for name in ("link", "unlink"):
        p = commands.add_parser(name, help="连接节点" if name == "link" else "移除边")
        p.add_argument("parent", type=int, help="边的来源节点 ID")
        p.add_argument("child", type=int, help="边的目标节点 ID")
        if name == "link":
            edge_options(p, required=True)
    p = commands.add_parser("edge", help="查看或修改边文本")
    sub = p.add_subparsers(dest="edge_command", required=True)
    for name in ("show", "edit", "append"):
        p = sub.add_parser(name, help=EDGE_COMMANDS[name][0])
        p.add_argument("parent", type=int, help="边的来源节点 ID")
        p.add_argument("child", type=int, help="边的目标节点 ID")
        if name != "show":
            edge_options(p)
    p = commands.add_parser("rm", help="删除没有连接的节点")
    p.add_argument("id", type=int, help="已有节点的整数 ID")
    commands.add_parser("export", help="以 JSON 导出整个图")
    for name, command_parser in commands.choices.items():
        description, details = COMMANDS[name]
        command_parser.description = description
        command_parser.epilog = details + "\n\n" + GLOBAL_NOTE
    for name, command_parser in sub.choices.items():
        description, details = EDGE_COMMANDS[name]
        command_parser.description = description
        command_parser.epilog = details + "\n\n" + GLOBAL_NOTE
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
        return await graph.add(read_text(args), args.parent, args.observation, args.action,
                               conclusion=args.conclusion, code_dir=args.code_dir)
    if command in ("edit", "append"):
        return await graph.update_text(read_text(args), node_id=args.id, append=command == "append")
    if command == "set-conclusion":
        return await graph.set_conclusion(args.id, read_text(args))
    if command == "set-code-dir":
        return await graph.set_code_dir(args.id, args.path)
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
        return await graph.link(args.parent, args.child, args.observation, args.action)
    if command == "unlink":
        return await graph.unlink(args.parent, args.child)
    if command == "edge":
        if args.edge_command == "show":
            return await graph.edge(args.parent, args.child)
        return await graph.update_edge(args.parent, args.child, args.observation, args.action,
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


def display_width(text):
    return sum(0 if unicodedata.combining(char) else
               2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
               for char in text)


def tree_summary(text):
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return "（空）"
    summary = preview(lines[first])
    remaining = len(lines) - first - 1
    if remaining:
        summary += f" …（另 {remaining} 行）"
    return summary


def render_tree(data, depth, full=False):
    width = shutil.get_terminal_size(fallback=(100, 24)).columns

    def emit(text, first_prefix, continuation=None):
        continuation = first_prefix if continuation is None else continuation
        for line in text.expandtabs(4).split("\n"):
            prefix = first_prefix
            chunk = ""
            used = display_width(prefix)
            for char in line:
                size = display_width(char)
                if chunk and used + size > width - 1:
                    print(prefix + chunk)
                    prefix, chunk = continuation, ""
                    used = display_width(prefix)
                chunk += char
                used += size
            print(prefix + chunk)
            first_prefix = continuation

    nodes = {n["id"]: n for n in data["nodes"]}
    outgoing = {}
    for edge in data["edges"]:
        outgoing.setdefault(edge["parent_id"], []).append(edge)
    seen = set()
    stack = [(root, "", "", 0, None) for root in reversed(data["roots"])]
    while stack:
        node_id, prefix, connector, level, edge = stack.pop()
        repeated = node_id in seen
        node = nodes[node_id]
        child_prefix = prefix + ("    " if connector == "└── " else "│   " if connector else "")
        children = outgoing.get(node_id, []) if not repeated and (depth is None or level < depth) else []
        title = f"[{node_id}] " + ("↩ " if repeated else "") + tree_summary(node["text"])
        emit(title, prefix + connector, child_prefix + "    ")
        fields = []
        if edge is not None:
            fields.extend((("观察", edge["observation"]), ("行动", edge["action"])))
        if not repeated:
            if full:
                fields.append(("文本", node["text"]))
            fields.append(("结论", node["conclusion"] if node["conclusion"] is not None else "尚未形成结论"))
        detail_prefix = child_prefix + ("│   " if children else "")
        scores = [f"{label}={number(node[key])}" for label, key in
                  (("value", "value"), ("subtree", "subtree_value")) if node[key] is not None]
        if scores and not repeated:
            emit("  ".join(scores), detail_prefix)
        for index, (label, text) in enumerate(fields):
            if full:
                last = index == len(fields) - 1
                emit(label, detail_prefix + ("└─ " if last else "├─ "))
                emit(text, detail_prefix + ("   " if last else "│  "))
            else:
                emit(tree_summary(text), detail_prefix + label + "：",
                     detail_prefix + "      ")
        if stack or children:
            print(child_prefix.rstrip())
        if repeated:
            continue
        seen.add(node_id)
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
        print(f"Code directory:     {result['code_dir'] if result['code_dir'] is not None else '—'}")
        print("\nText:\n" + result["text"])
        print("\nConclusion:\n" + (result["conclusion"] if result["conclusion"] is not None else "—"))
        for label, key in (("Incoming", "incoming"), ("Outgoing", "outgoing")):
            print(f"\n{label}:")
            for edge in result[key]:
                print(f"{edge['parent_id']} -> {edge['child_id']}\n{edge_text(edge)}")
    elif command == "list":
        print("ID\tVALUE\tSUBTREE\tSCORED/TOTAL\tTEXT\tCONCLUSION")
        for node in result:
            conclusion = preview(node["conclusion"]) if node["conclusion"] is not None else "尚未形成结论"
            print(f"{node['id']}\t{number(node['value'])}\t{number(node['subtree_value'])}\t"
                  f"{node['scored_descendant_count']}/{node['descendant_count']}\t{preview(node['text'])}\t{conclusion}")
    elif command == "search":
        for match in result:
            label = str(match["id"]) if match["type"] == "node" else f"{match['parent_id']} -> {match['child_id']}"
            content = match["text"] if match["type"] == "node" else edge_text(match)
            print(f"{match['type']} {label}\n{content}\n")
    elif command == "tree":
        render_tree(result, args.depth, args.full)
    elif command == "edge" and args.edge_command == "show":
        print(f"{result['parent_id']} -> {result['child_id']}")
        print(f"Created: {result['created_at']}\nUpdated: {result['updated_at']}\n\n{edge_text(result)}")
    elif "parent_id" in result:
        print(f"OK {result['parent_id']} -> {result['child_id']}")
    else:
        print(f"OK {result['id']}")


def normalize_globals(argv):
    """Accept --db and --json before or after subcommands, preserving text arguments."""
    leading, trailing = [], []
    # Skip values belonging to text options even when they resemble global flags.
    value_options = {"--text", "--file", "--observation", "--action", "--conclusion", "--code-dir", "--parent", "--sort", "--limit", "--depth", "--in"}
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
        write = args.command in {"add", "edit", "append", "set-value", "clear-value", "set-conclusion", "set-code-dir", "link", "unlink", "rm"} or (
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
        if args.command in ("add", "link", "edge") and hasattr(args, "observation"):
            Graph.validate_edge_fields(args.observation, args.action)
            if args.command == "add":
                has_parent = args.parent is not None
                has_observation = args.observation is not None
                has_action = args.action is not None
                if not (has_parent == has_observation == has_action):
                    raise GraphError("invalid_arguments", "--parent、--observation 和 --action 必须一起使用。", 2)
            elif args.command == "edge" and args.observation is None and args.action is None:
                raise GraphError("invalid_arguments", "至少指定 --observation 或 --action。", 2)
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
