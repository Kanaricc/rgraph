# rgraph

用 SQLite 保存研究过程的文本 DAG，通过 CLI 操作。节点和边均保存任意文本，工具不解释文本结构，也不执行研究。需要 Python 3.11+，无运行时第三方依赖。

## 安装

在项目目录执行：

```bash
uv sync
uv run rgraph --help
```

也可安装为用户级命令：

```bash
uv tool install .
rgraph --version
```

## 基本使用

一个数据库文件对应一张图，默认操作当前目录的 `research.db`。开启独立研究时另建数据库。

```bash
rgraph init
rgraph add --text "研究问题及初步计划"
# 输出 1；新节点尚未设置价值

rgraph append 1 --file result.md
rgraph set-value 1 0.4

rgraph add --parent 1 --edge-text "扩大样本量" --file next-plan.md
# 输出 2
rgraph set-value 2 0.8

rgraph show 1
rgraph tree
rgraph --json show 1
rgraph --db another.db init
```

节点 ID 为数据库内递增整数，删除后不会复用。同一对节点只有一条边；允许多个根、分支和汇合。新增连接会检查节点存在、重复边、自连接和环。创建子节点及父边是同一事务，失败时不留下半成品。

## 命令接口

```text
rgraph [--db PATH] [--json] COMMAND ...

init
add (--text TEXT | --file PATH) [--parent ID --edge-text TEXT]
edit ID (--text TEXT | --file PATH)
append ID (--text TEXT | --file PATH)
set-value ID VALUE
clear-value ID
show ID [--text-only]
list [--roots] [--unscored]
     [--sort id|value|subtree-value|updated] [--desc] [--limit N]
search QUERY [--in nodes|edges|all]
tree [ID] [--depth N]
link PARENT CHILD (--text TEXT | --file PATH)
unlink PARENT CHILD
edge show PARENT CHILD
edge edit PARENT CHILD (--text TEXT | --file PATH)
edge append PARENT CHILD (--text TEXT | --file PATH)
rm ID
export
```

全局参数也可放在子命令后。各命令支持 `--help`，版本使用 `--version`。

### 文本输入

`--text` 和 `--file` 必须且只能选择一个；`--file -` 读取标准输入。文件按 UTF-8 读取，保留换行。空文本也可保存。

```bash
cat plan.md | rgraph add --file -
rgraph edit 2 --file revised.md
rgraph append 2 --text "补充实验结果"
rgraph show 2 --text-only > node.md
```

`edit` 替换全文；`append` 在非空原文和新增文本之间插入一个换行。工具只保存当前文本及时间，不保存修订历史。`show --text-only` 原样输出节点文本，不额外添加换行，不能与 `--json` 同用。

### 边与汇合

`add` 最多指定一个父节点，且 `--parent` 和 `--edge-text` 必须一起使用。更多入边使用 `link` 添加，各边分别保存文本：

```bash
rgraph link 3 4 --text "结合节点 3 的发现"
rgraph edge show 3 4
rgraph edge edit 3 4 --file direction.md
rgraph edge append 3 4 --text "补充：保持评估集不变"
rgraph unlink 3 4
```

`unlink` 只删除边。`rm` 仅删除没有任何入边和出边的节点；有连接时先显式 `unlink`，不提供递归删除。

### 价值计算

`add` 不接受价值参数。`set-value` 后续设置 `[0, 1]` 内的有限数值，`clear-value` 恢复未评估状态。`0` 是已评估的零价值，`NULL` 是尚未评估。

子树价值在查询时计算：

```text
子树价值 = 所有已评估的可达后代的价值之和 / 已评估后代数量
```

不包含自身；共享后代按 ID 去重；未评估节点不参与均值，但继续遍历其后代。无已评估后代（包括叶节点）时返回 `NULL`。同时输出后代总数和已评估数量。

### 查询

```bash
rgraph list --roots
rgraph list --unscored
rgraph list --sort subtree-value --desc --limit 20
rgraph search "对照组" --in edges
rgraph tree 1 --depth 3
```

`list` 默认按 ID 升序，未指定数量则列出全部。价值为空时始终排最后。文本摘要取第一个非空行，最多 60 字符。

搜索是区分大小写的字面子串匹配，不解释正则、`%` 或 `_`。默认搜索节点和边。

`tree` 默认从全部根展开，也可指定起点。起点深度为 0；未指定深度则完整展开。边文本完整显示；共享节点首次出现时展开，再次出现时显示 `↩`，不会重复展开。深度限制按首次出现路径应用。子树价值始终根据全部后代计算，不受显示深度限制。

## JSON 与退出码

`--json` 输出完整对象，不截断文本。`show` 包含 `id`、`text`、`value`、`subtree_value`、`descendant_count`、`scored_descendant_count`、时间及 `incoming` / `outgoing` 边列表。`list` 和 `search` 返回数组；搜索项通过 `type` 区分 `node` / `edge`。

`tree --json` 返回 `roots`（起点 ID）、`nodes`（带价值统计的节点数组）和 `edges`（展开的边数组）。所有时间使用 UTC ISO 8601。

修改命令在 JSON 模式返回修改后的节点或边；`rm` 返回 `{"id": ID}`，`unlink` 返回 `{"parent_id": ID, "child_id": ID}`。默认 `add` 只输出新 ID，其余修改命令输出简短确认。

成功结果写入 stdout，错误写入 stderr。JSON 错误格式：

```json
{"error": {"code": "cycle_detected", "message": "连接 4 -> 1 会形成环。"}}
```

| 退出码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 文件、数据库、编码等执行错误 |
| 2 | 参数错误，包括价值越界 |
| 3 | 节点或边不存在 |
| 4 | 重复边、形成环、删除仍有连接的节点、初始化目标已存在等冲突 |

业务错误码包括 `invalid_arguments`、`node_not_found`、`edge_not_found`、`self_link`、`edge_exists`、`cycle_detected`、`node_connected`、`database_exists`、`invalid_database`；其他执行错误使用 `execution_error`。

除 `init` 外，命令不会创建数据库。所有修改在单个事务中执行，查询使用一致的数据库快照。程序不弹确认问题，也不启动编辑器。

## 导出与备份

```bash
rgraph export > research.json
```

`export` 始终输出 JSON，包含 `schema_version`、全部原始 `nodes` 和 `edges`，包括时间，不包含可重新计算的子树价值。第一版不提供导入或跨库合并。无命令写入时，可复制 SQLite 文件备份。

## 项目结构

- `src/rgraph/storage.py`：SQLite 表结构、事务内图操作、价值计算。
- `src/rgraph/cli.py`：参数解析、文本输入、终端和 JSON 输出、退出码。
- `pyproject.toml`：Python 包和 `rgraph` 命令入口。

使用标准库 `sqlite3` 和 `argparse`。查询列表时逐节点计算后代均值，适合本地研究记录；目前没有对子树值做缓存。
