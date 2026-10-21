# rgraph

用 SQLite 保存研究过程的文本 DAG，通过 CLI 操作。节点保存任意文本，以及独立的结论和实验代码目录；边保存两个必填文本字段：`observation`（导致改进的观测原因）和 `action`（下一步要做什么）。工具不解释节点文本结构，也不执行研究。需要 Python 3.11+，使用 Tortoise ORM 访问 SQLite。

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
rgraph set-conclusion 1 --file conclusion.md
rgraph set-code-dir 1 ./experiments/baseline
rgraph set-value 1 0.4

rgraph add --parent 1 --observation "当前样本量不足以支持结论" --action "扩大样本量" --file next-plan.md
# 输出 2
rgraph set-value 2 0.8

rgraph show 1
rgraph tree
rgraph --json show 1
rgraph --db another.db init
```

节点 ID 为数据库内递增整数，删除后不会复用。同一对节点只有一条边；只允许在空图中创建无父节点的起点，后续节点必须从已有节点创建；允许分支和汇合。新增连接会检查节点存在、重复边、自连接和环。创建子节点及父边是同一事务，失败时不留下半成品。

## 命令接口

```text
rgraph [--db PATH] [--json] COMMAND ...

init
add (--text TEXT | --file PATH) [--conclusion TEXT] [--code-dir PATH]
    [--parent ID --observation TEXT --action TEXT]
edit ID (--text TEXT | --file PATH)
append ID (--text TEXT | --file PATH)
set-conclusion ID (--text TEXT | --file PATH)
set-code-dir ID PATH
set-value ID VALUE
clear-value ID
show ID [--text-only]
list [--roots] [--unscored]
     [--sort id|value|subtree-value|updated] [--desc] [--limit N]
search QUERY [--in nodes|edges|all]
tree [ID] [--depth N]
link PARENT CHILD --observation TEXT --action TEXT
unlink PARENT CHILD
edge show PARENT CHILD
edge edit PARENT CHILD [--observation TEXT] [--action TEXT]
edge append PARENT CHILD [--observation TEXT] [--action TEXT]
rm ID
export
```

全局参数也可放在子命令后。`rgraph --help` 包含完整起步流程、图约束及自动化约定；每个命令（包括 `edge show/edit/append`）的 `--help` 提供前置条件、参数、输出和示例。版本使用 `--version`。

### 文本输入

节点的 `--text` 和 `--file` 必须且只能选择一个；`--file -` 读取标准输入。文件按 UTF-8 读取，保留换行。空文本也可保存。

```bash
cat plan.md | rgraph add --file -
rgraph edit 2 --file revised.md
rgraph append 2 --text "补充实验结果"
rgraph show 2 --text-only > node.md
```

`edit` 替换全文；`append` 在非空原文和新增文本之间插入一个换行。工具只保存当前文本及时间，不保存修订历史。`show --text-only` 原样输出节点文本，不额外添加换行，不能与 `--json` 同用。

### 结论和实验代码目录

节点的 `conclusion` 和 `code_dir` 是独立字段，新建时可以留空（JSON 为 `null`），后续单独设置。未补齐这两个字段的节点不能创建子节点或作为 `link` 的父节点；补齐后才允许继续研究。展开时重新检查实验目录和 README，目录失效或 README 被删除也会阻止操作。结论不从节点文本中提取，设置后替换原结论，拒绝空白内容。

```bash
rgraph set-conclusion 2 --text "扩大样本后，改进效果仍然稳定"
rgraph set-conclusion 2 --file conclusion.md
rgraph set-code-dir 2 ./experiments/expanded-sample

# 在空图中创建起点时，也可一起填写
rgraph add --file plan.md --conclusion "已验证初步假设" --code-dir ./experiments/baseline
```

写入或更换实验代码目录时，要求目录存在，且根部至少有一个普通 README 文件。文件名不区分大小写，接受 `README`、`README.md`、`README.rst` 等 `README.*` 名称。子目录中的 README 不计入；名为 README 的目录也不计入。

缺少文件时报 `readme_required`（退出码 2），提示补全复现实验的 README，整个操作不写入数据库。README 应说明环境、运行步骤及结果复现方式；工具仅检查文件存在，不判断内容是否完整。

相对目录按命令执行时的工作目录解析，支持 `~`，以解析后的绝对路径保存。查询时不重新检查目录，也不复制实验代码；移动目录后需重新设置路径。`show` 显示结论和目录，JSON 查询及导出均包含两个字段；搜索节点时也搜索结论。终端 `tree` 在节点摘要下完整显示结论，便于沿研究路线查看各阶段判断；未设置时显示“尚未形成结论”。

### 边与汇合

空图中的第一个节点可省略父节点；数据库非空后，`add` 必须指定已有父节点，否则返回 `parent_required`。节点创建与父边写入在同一事务内，父节点不完整时返回 `node_incomplete`，不留下新节点。该规则针对创建操作；`unlink` 仍允许断开已有连接。

`add` 最多指定一个父节点，`--parent`、`--observation` 和 `--action` 必须一起使用。`link` 创建边时同样要求两个字段。字段不可为空或仅含空白，内容按原样保存。

`edge edit` 替换指定字段，`edge append` 向指定字段追加一个换行及新内容；两者至少指定一个字段，未指定的字段保持原值。边不再接受 `--text`、`--file` 或 `--edge-text`。

```bash
rgraph link 3 4 --observation "节点 3 显示参数影响结果" --action "固定样本集并调整参数"
rgraph edge show 3 4
rgraph edge edit 3 4 --action "调整参数，并增加对照组"
rgraph edge append 3 4 --observation "重复实验中也出现了相同现象"
rgraph unlink 3 4
```

`unlink` 只删除边。`rm` 仅删除没有任何入边和出边的节点；有连接时先显式 `unlink`，不提供递归删除。

### 价值计算

价值由用户人工评估。`set-value` 和 `clear-value` 仅供用户使用，禁止 Agent 自行调用；Agent 不得自行评分、调整或清除评分。Agent 可以读取已有价值，但价值及子树均值不代表结论可信度或下一轮试错优先级。

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

`list` 默认按 ID 升序，未指定数量则列出全部。价值为空时始终排最后。TEXT 和 CONCLUSION 列分别显示正文和结论摘要，取第一个非空行，最多 60 字符；未设置结论显示“尚未形成结论”。

搜索是区分大小写的字面子串匹配，不解释正则、`%` 或 `_`。默认搜索节点文本、结论及边的 observation、action 字段。

`tree` 默认从全部根展开，也可指定起点。起点深度为 0；未指定深度则完整展开。边的 observation、action 完整显示；共享节点首次出现时展开，再次出现时显示 `↩`，不会重复展开。深度限制按首次出现路径应用。子树价值始终根据全部后代计算，不受显示深度限制。

## JSON 与退出码

`--json` 输出完整对象，不截断文本。`show` 包含 `id`、`text`、`conclusion`、`code_dir`、`value`、`subtree_value`、`descendant_count`、`scored_descendant_count`、时间及 `incoming` / `outgoing` 边列表。`list` 和 `search` 返回数组；搜索项通过 `type` 区分 `node` / `edge`。

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
| 2 | 参数错误，包括价值越界、结论为空、实验目录无效或缺少 README |
| 3 | 节点或边不存在 |
| 4 | 重复边、形成环、删除仍有连接的节点、缺少父节点、父节点未补齐、初始化目标已存在等冲突 |

业务错误码包括 `invalid_arguments`、`parent_required`、`node_incomplete`、`invalid_code_dir`、`readme_required`、`node_not_found`、`edge_not_found`、`self_link`、`edge_exists`、`cycle_detected`、`node_connected`、`database_exists`、`invalid_database`；其他执行错误使用 `execution_error`。

除 `init` 外，命令不会创建数据库。所有修改在单个事务中执行，查询使用一致的数据库快照。程序不弹确认问题，也不启动编辑器。

## 导出与备份

```bash
rgraph export > research.json
```

`export` 始终输出 JSON，包含 `schema_version`、全部原始 `nodes` 和 `edges`，包括时间，不包含可重新计算的子树价值。第一版不提供导入或跨库合并。无命令写入时，可复制 SQLite 文件备份。

## 项目结构

- `src/rgraph/models.py`：节点、边的 Tortoise ORM 模型及关系约束。
- `src/rgraph/storage.py`：ORM 生命周期、事务内图操作、价值计算。
- `src/rgraph/cli.py`：参数解析、文本输入、终端和 JSON 输出、退出码。
- `pyproject.toml`：Python 包和 `rgraph` 命令入口。

使用 Tortoise ORM 和标准库 `argparse`。CLI 通过单个异步入口管理连接，写事务先取得 SQLite 写锁，再检查和修改图，避免并发连接破坏 DAG 约束。

数据库版本为 4：节点新增可空的 `conclusion`、`code_dir` 字段，边使用 `observation` 和 `action`。CLI、JSON 输出及导出均使用这些字段，继续用父子节点 ID 标识边，不暴露内部 ID。旧版数据库会返回 `invalid_database`，本版不提供旧库迁移。价值范围与禁止自连接由初始化时创建的触发器约束，普通数据操作通过 ORM 完成。

查询列表时逐节点计算后代均值，适合本地研究记录；目前没有对子树值做缓存。字面搜索在 ORM 读取文本后进行，保持大小写敏感及 `%`、`_` 的字面语义。
