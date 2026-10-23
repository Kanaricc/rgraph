# rgraph

A CLI for storing research progress as a text DAG in SQLite. Nodes hold a strictly structured YAML experiment plan, a separate conclusion, and an experiment code directory. Edges have two required text fields: `observation` (the observation motivating a change) and `action` (what to do next). The tool validates the plan structure but does not evaluate its scientific content or conduct research. Requires Python 3.11+ and uses Tortoise ORM to access SQLite.

## Installation

Run from the project directory:

```bash
uv sync
uv run rgraph --help
```

Alternatively, install it as a user-level command:

```bash
uv tool install .
rgraph --version
```

## Basic usage

Each database file holds one graph. By default, commands use `research.db` in the current directory. Use a separate database for an independent research project.

```bash
rgraph init
rgraph add --file plan.example.yaml
# Prints 1; the new node has no value score yet.

# Save detailed results in the experiment directory.
rgraph set-conclusion 1 --file conclusion.md
rgraph set-code-dir 1 ./experiments/baseline
rgraph set-value 1 0.4  # Human evaluation only; agents must not assign scores.

rgraph add --parent 1 --observation "The current sample is too small to support the conclusion" --action "Increase the sample size" --file next-plan.yaml
# Prints 2.
rgraph set-value 2 0.8  # Human evaluation only.

rgraph show 1
rgraph tree
rgraph --json show 1
rgraph --db another.db init
```

Node IDs are increasing integers within a database and are not reused after deletion. Each ordered pair of nodes can have only one edge. A node without a parent can only be created in an empty graph; subsequent nodes must be created from existing nodes. Branching and merging are supported. New connections are checked for missing nodes, duplicate edges, self-links, and cycles. Creating a child node and its parent edge is a single transaction; failures leave neither partially created.

## Command reference

```text
rgraph [--db PATH] [--json] COMMAND ...

init
add (--text TEXT | --file PATH) [--conclusion TEXT] [--code-dir PATH]
    [--parent ID --observation TEXT --action TEXT]
edit ID (--text TEXT | --file PATH)
set-conclusion ID (--text TEXT | --file PATH)
set-code-dir ID PATH
set-value ID VALUE
clear-value ID
show ID [--text-only]
list [--roots] [--unscored]
     [--sort id|value|subtree-value|updated] [--desc] [--limit N]
search QUERY [--in nodes|edges|all]
tree [ID] [--depth N] [--full]
link PARENT CHILD --observation TEXT --action TEXT
unlink PARENT CHILD
edge show PARENT CHILD
edge edit PARENT CHILD [--observation TEXT] [--action TEXT]
edge append PARENT CHILD [--observation TEXT] [--action TEXT]
rm ID
export
```

Global options can also appear after a subcommand. `rgraph --help` includes a complete getting-started workflow, graph constraints, and automation conventions. Each command's `--help`, including `edge show/edit/append`, describes prerequisites, arguments, output, and examples. Use `--version` to display the version.

### Text input

Specify exactly one of `--text` and `--file` for node text. `--file -` reads standard input. Files are read as UTF-8 with line breaks preserved. Node text must be a complete experiment plan matching the structure below.

```bash
cat plan.yaml | rgraph add --file -
rgraph edit 2 --file revised-plan.yaml
rgraph show 2 --text-only > node.yaml
```

`add` and `edit` validate the complete plan before writing. `edit` replaces the entire plan; keep detailed results in the experiment directory. Invalid plans return `invalid_plan` (exit code 2) without changing the database. Original YAML formatting is preserved. The tool stores only the current text and timestamps, without revision history. `show --text-only` outputs the node text exactly as stored, without adding a trailing newline, and cannot be combined with `--json`.

### Experiment plan structure

Use [plan.example.yaml](plan.example.yaml) as a starting point. Each node text must contain one YAML document with exactly these fields:

```yaml
plan_version: 1
title: Experiment title
question: |
  The specific question this experiment will answer.
hypothesis: |
  The testable hypothesis and its basis.
design: |
  Experimental conditions, baseline, variables, and controls.
evaluation: |
  Data selection, metric definitions, repetitions, and aggregation.
decision:
  supported: |
    Conditions under which the hypothesis is supported.
  not_supported: |
    Conditions under which a valid experiment does not support the hypothesis.
  inconclusive: |
    Conditions under which the evidence is insufficient to decide.
execution:
  environment: |
    - Identify each machine and the CPU, GPU, memory, or other resources to use.
    - List read-only files and directories with their machine and absolute path.
    - List read-write files and directories, including environments, caches, and temporary files.
    - Describe the software environment.
  steps: |
    Describe the execution steps in order.
  prohibited_actions: |
    Describe prohibited actions, or explicitly state that there are no additional prohibitions.
  artifacts: |
    Describe final deliverables, which can be files or network links, and their locations.
  stop_condition: |
    Describe completion criteria, resource limits, and conditions requiring an early stop.
```

All fields are required, and unknown or duplicate fields are rejected at every object level. `plan_version` must be the integer `1`; all other leaf values must be nonempty strings after whitespace is stripped. In particular, `hypothesis`, `design`, `evaluation`, and every field under `execution` are plain text, not nested objects or YAML lists. Use `|` to preserve intentional line breaks without wrapping sentences to a fixed width.

Validation checks structure and types, not whether the prose describes a sound experiment or whether declared permissions are obeyed. The plan does not replace the separate `conclusion` and `code_dir` fields. Existing stored text remains readable; any subsequent text write must pass validation. Database schema version remains 4.

### Conclusions and experiment code directories

A node's `conclusion` and `code_dir` are separate fields. Both may be left unset when creating a node (`null` in JSON) and set later. A node cannot have children added or be used as the parent of a `link` until both fields are populated. The experiment directory and README are checked again when extending a node; an invalid directory or a deleted README also blocks the operation. Conclusions are not extracted from node text. Set `conclusion` only after the experiment has finished, using a concrete conclusion based on actual results. Placeholder content such as “pending experiment”, “TODO”, or “to be filled in” is prohibited; leave the field unset until the experiment is finished. Setting a conclusion replaces the previous one; null, empty, or whitespace-only conclusions are rejected. A parent that already has children must not have its conclusion cleared, but it may be replaced with a new concrete conclusion.

```bash
rgraph set-conclusion 2 --text "The improvement remains stable with a larger sample"
rgraph set-conclusion 2 --file conclusion.md
rgraph set-code-dir 2 ./experiments/expanded-sample

# These fields can also be supplied when creating the starting node in an empty graph.
rgraph add --file plan.md --conclusion "The initial hypothesis has been validated" --code-dir ./experiments/baseline
```

When setting or changing an experiment code directory, the directory must exist and contain at least one regular README file at its root. Filenames are case-insensitive; `README`, `README.md`, `README.rst`, and other `README.*` names are accepted. READMEs in subdirectories and directories named README do not count.

A missing README produces `readme_required` (exit code 2), asking for a README describing how to reproduce the experiment. The operation makes no database changes. The README should explain the environment, execution steps, and how to reproduce the results. The tool checks only that the file exists, not whether its contents are complete.

Relative directories are resolved against the command's working directory. `~` is supported, and the resolved absolute path is stored. Queries do not recheck directories or copy experiment code; update the stored path after moving a directory. `show` displays the conclusion and directory, and both fields are included in JSON queries and exports. Node searches also include conclusions. Terminal `tree` output displays a conclusion summary below each node; use `tree --full` to read complete conclusions and node text along the research path. Unset conclusions are displayed as “尚未形成结论” (“No conclusion yet”).

### Edges and merging

The first node in an empty graph may omit a parent. Once the database is nonempty, `add` requires an existing parent or returns `parent_required`. The node and parent edge are created in one transaction. An incomplete parent produces `node_incomplete` without leaving a new node behind. This rule applies to creation; `unlink` can still disconnect existing nodes.

`add` accepts at most one parent. `--parent`, `--observation`, and `--action` must be supplied together. `link` also requires both text fields when creating an edge. These fields cannot be empty or whitespace-only, and their contents are stored unchanged.

`edge edit` replaces the specified fields. `edge append` appends a newline and new content to the specified fields. Both commands require at least one field; unspecified fields remain unchanged. Edges no longer accept `--text`, `--file`, or `--edge-text`.

```bash
rgraph link 3 4 --observation "Node 3 shows that the parameter affects the result" --action "Fix the sample set and adjust the parameter"
rgraph edge show 3 4
rgraph edge edit 3 4 --action "Adjust the parameter and add a control group"
rgraph edge append 3 4 --observation "The same effect appeared in repeated experiments"
rgraph unlink 3 4
```

`unlink` deletes only the edge. `rm` deletes only nodes with no incoming or outgoing edges. Explicitly `unlink` connected nodes first; recursive deletion is not supported.

### Value calculation

Values are evaluated manually by the user. `set-value` and `clear-value` are for human users only; agents must not invoke them on their own to assign, adjust, or clear scores. Agents may read existing values, but neither a value nor a subtree mean represents confidence in a conclusion or the priority of the next experiment.

`add` does not accept a value argument. Use `set-value` afterward to assign a finite number in `[0, 1]`, or `clear-value` to restore the unscored state. `0` means an evaluated value of zero; `NULL` means not yet evaluated.

Subtree values are calculated at query time:

```text
subtree value = sum of values of all scored reachable descendants / number of scored descendants
```

The node itself is excluded. Shared descendants are deduplicated by ID. Unscored nodes are excluded from the mean, but their descendants are still traversed. If there are no scored descendants, including for leaf nodes, the result is `NULL`. The total descendant count and scored descendant count are also returned.

### Queries

```bash
rgraph list --roots
rgraph list --unscored
rgraph list --sort subtree-value --desc --limit 20
rgraph search "control group" --in edges
rgraph tree 1 --depth 3
```

`list` sorts by ID in ascending order by default and lists all nodes unless a limit is specified. Null values always sort last. The TEXT and CONCLUSION columns show summaries of the body text and conclusion respectively, using the first nonempty line, truncated to at most 60 characters. Unset conclusions are displayed as “尚未形成结论” (“No conclusion yet”).

Search uses case-sensitive literal substring matching. Regular expressions, `%`, and `_` are not interpreted. By default, it searches node text, conclusions, and the `observation` and `action` fields of edges.

`tree` starts from all roots by default, or from a specified node. The starting node is at depth 0. The entire graph is expanded unless a depth limit is specified. Branches connect nodes directly; each child's incoming observation and action appear below that child. By default, node text, conclusions, observations, and actions show the first nonempty line, truncated to at most 60 characters, with a remaining-line count for multiline content. Unset value fields are hidden. Use `rgraph tree 2 --full` to display complete node text, conclusions, observations, and actions with paragraph breaks preserved. Long lines wrap to the terminal width while retaining tree guides and indentation.

Shared nodes are expanded on their first appearance; subsequent appearances show `↩` and their incoming edge information without repeating node details. Depth limits follow the first path on which a node is encountered. Subtree values always include all descendants, regardless of the display depth limit. JSON output always includes complete text regardless of `--full`.

## JSON and exit codes

`--json` outputs complete objects without truncating text. `show` includes `id`, `text`, `conclusion`, `code_dir`, `value`, `subtree_value`, `descendant_count`, `scored_descendant_count`, timestamps, and the `incoming` / `outgoing` edge lists. `list` and `search` return arrays. Search results use `type` to distinguish `node` and `edge` items.

`tree --json` returns `roots` (starting node IDs), `nodes` (nodes with value statistics), and `edges` (expanded edges). All timestamps use UTC ISO 8601.

In JSON mode, mutation commands return the updated node or edge. `rm` returns `{"id": ID}`, and `unlink` returns `{"parent_id": ID, "child_id": ID}`. In default output mode, `add` prints only the new ID; other mutation commands print a short confirmation.

Successful output goes to stdout; errors go to stderr. JSON errors have this structure (the message below is translated from the CLI's Chinese output):

```json
{"error": {"code": "cycle_detected", "message": "Connecting 4 -> 1 would create a cycle."}}
```

| Exit code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Execution errors, such as file, database, or encoding errors |
| 2 | Argument errors, including an invalid experiment plan, an out-of-range value, an empty conclusion, an invalid experiment directory, or a missing README |
| 3 | Node or edge not found |
| 4 | Conflicts, including duplicate edges, cycles, deletion of a connected node, a missing parent, an incomplete parent, or an existing initialization target |

Application error codes include `invalid_plan`, `invalid_arguments`, `parent_required`, `node_incomplete`, `invalid_code_dir`, `readme_required`, `node_not_found`, `edge_not_found`, `self_link`, `edge_exists`, `cycle_detected`, `node_connected`, `database_exists`, and `invalid_database`. Other execution errors use `execution_error`.

Only `init` creates a database. All mutations run in a single transaction, and queries use a consistent database snapshot. The program does not prompt for confirmation or launch an editor.

## Export and backup

```bash
rgraph export > research.json
```

`export` always outputs JSON containing `schema_version` and all raw `nodes` and `edges`, including timestamps. It excludes subtree values, which can be recalculated. The initial version does not support import or merging across databases. Copy the SQLite file to make a backup when no commands are writing to it.

## Project structure

- `src/rgraph/plans.py`: Strict YAML experiment-plan validation.
- `src/rgraph/models.py`: Tortoise ORM models and relationship constraints for nodes and edges.
- `src/rgraph/storage.py`: ORM lifecycle, transactional graph operations, and value calculation.
- `src/rgraph/cli.py`: Argument parsing, text input, terminal and JSON output, and exit codes.
- `pyproject.toml`: Python package metadata and the `rgraph` command entry point.

The project uses Tortoise ORM, PyYAML for plan parsing, and the standard-library `argparse` module. The CLI manages connections through a single asynchronous entry point. Write transactions acquire a SQLite write lock before checking and modifying the graph, preventing concurrent connections from violating DAG constraints.

Database schema version 4 adds nullable `conclusion` and `code_dir` node fields and uses `observation` and `action` on edges. These fields are used throughout the CLI, JSON output, and exports. Edges are still identified by parent and child node IDs; internal edge IDs are not exposed. Older databases return `invalid_database`; this version does not provide migration from older schemas. Value bounds and the prohibition on self-links are enforced by triggers created during initialization. Regular data operations use the ORM.

List queries calculate descendant means separately for each node, which suits local research records. Subtree values are not currently cached. Literal search is performed after reading text through the ORM, preserving case sensitivity and treating `%` and `_` literally.
