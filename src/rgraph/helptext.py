"""CLI help: workflow, command semantics, and examples."""

OVERVIEW = """用 SQLite 保存研究 DAG，通过文本节点和带 observation/action 的边记录研究演进。
节点字段：text、conclusion、code_dir、value；工具不执行实验。

开始使用（示例 ID 假定从空库开始；实际使用 add 返回的 ID）：
  rgraph init
  rgraph add --text "基线研究计划"
  # 在 ./experiments/baseline 完成实验，并编写根部 README.md 说明复现方式。
  rgraph append 1 --text "实验结果：样本量不足"
  rgraph set-conclusion 1 --text "当前结果需要更多样本验证"
  rgraph set-code-dir 1 ./experiments/baseline
  # 价值由用户人工评估；Agent 禁止自行调用 set-value / clear-value。
  rgraph add --parent 1 --observation "样本量不足" --action "扩大样本量" --text "下一轮计划"
  rgraph tree
  rgraph --json show 1

必须遵守：
  * conclusion 只能在实验结束后设置为基于实际结果的具体结论，禁止填写占位信息
    （如“待实验”“待补充”“TODO”）；实验未结束时保持未设置。
  * 已有子节点的父节点禁止清空 conclusion；可替换为新的具体结论。
  * 仅空图允许 add 不带父节点；之后必须指定已存在的 --parent。
  * 父节点有非空结论、实验目录及根部 README 后，才可 add 子节点或 link。
    写入目录和展开父节点时均检查目录及 README，缺失则报错。
  * 边的 observation 是观测原因，action 是后续动作；创建时两项必填且非空。
  * 允许分支、汇合；禁止自连接、重复边和环。多父节点用 link 补充入边。
  * value 由用户人工评估；set-value / clear-value 仅供用户使用，禁止 Agent 自行调用。
    Agent 不得自行评分、调整或清除评分；可以读取已有价值。
    value 范围 [0,1]；未评估为 null，与 0 不同。
    subtree 是已评估可达后代的均值，不含自身、共享后代去重，无值为 null。
    价值及子树均值不代表结论可信度或下一轮试错优先级。

输入与自动化：
  --text / --file 二选一，文件使用 UTF-8；--file - 读取标准输入。
  一个数据库文件是一项独立研究，默认当前目录 research.db。
  除 init 外不创建数据库；当前结构版本 4，旧版本不支持，无迁移命令。
  --db 和 --json 可放在子命令前后。add 默认仅输出新 ID；--json 返回对象。
  成功结果写 stdout，错误写 stderr；修改原子提交，失败整体回滚。
  --json 错误：{"error":{"code":"node_incomplete","message":"..."}}
  退出码：0 成功；1 文件/数据库错误；2 参数或目录/README 错误；
          3 节点/边不存在；4 操作冲突（父节点不完整、缺少父节点、环等）。
  每个命令提供 --help；边操作详见 rgraph edge --help。
"""

GLOBAL_NOTE = "全局参数：--db PATH（默认 research.db）、--json；可放在子命令前后。\n成功写 stdout，错误写 stderr；失败的修改整体回滚。"

COMMANDS = {
    "init": ("初始化一份独立研究数据库。", """目标文件必须不存在；已有文件返回 database_exists（退出码 4），不覆盖。
创建结构版本 4。父目录必须存在；其他命令要求先初始化。
默认输出初始化路径；--json 返回 database、schema_version。

示例：
  rgraph init
  rgraph --db ./another-research.db init
"""),
    "add": ("创建文本节点；图非空时必须从已有父节点增长。", """--text 与 --file 必选其一；--file - 读取标准输入。默认只输出新 ID，
--json 返回新节点（含入边、出边、价值统计）。新节点 value 始终为 null。

规则：
  空图可省略父节点；非空图必须提供 --parent、--observation、--action 三项。
  父节点必须有非空结论、有效实验目录和根部 README，否则拒绝创建。
  --conclusion、--code-dir 是新节点自己的字段，允许先留空再补充。
  --conclusion 只能在实验结束后填写基于实际结果的具体结论，禁止“待实验”、
  “待补充”、“TODO”等占位信息；实验未结束时省略此参数。
  提供结论时不可为空白；提供目录时立即校验。节点及父边在同一事务创建。
  失败：parent_required / node_incomplete（4），readme_required（2），
  node_not_found（3）。多父节点先 add，再使用 link 补充其余入边。

示例：
  rgraph add --file initial-plan.md
  rgraph add --parent 1 --observation "样本不足" --action "扩大样本" --file next.md
  rgraph add --parent 1 --observation "效果稳定" --action "复现结果" --text "复现计划" --code-dir ./experiment
"""),
    "edit": ("替换节点的完整 text 字段。", """--text 与 --file 必选其一，--file - 读取标准输入；允许空文本。
仅替换 text，不修改结论、实验目录、价值或连接；不保存旧版本。
默认输出 OK ID；--json 返回更新后的节点及相邻边和价值统计。

示例：
  rgraph edit 2 --file revised-plan.md
  rgraph edit 2 --text "新的完整研究记录"
"""),
    "append": ("向节点 text 追加实验记录。", """--text 与 --file 必选其一，--file - 读取标准输入。
原文非空时在原文和新增文本之间插入一个换行；原文为空则直接写入。
不更新独立结论字段；结论请用 set-conclusion。默认输出 OK ID，
--json 返回更新后的节点及相邻边和价值统计。

示例：
  rgraph append 2 --file result.md
  rgraph append 2 --text "观察：新增样本表现相同"
"""),
    "set-conclusion": ("设置或替换节点的独立研究结论。", """--text 与 --file 必选其一，--file - 读取标准输入；拒绝空白结论。
只能在实验结束后设置基于实际结果的具体结论，禁止“待实验”、“待补充”、
“TODO”等占位信息；实验未结束时保持未设置。
已有子节点的父节点禁止清空 conclusion；可替换为新的具体结论。
结论不从 text 提取，也不自动同步到 text。父节点必须有结论和带 README
的实验目录才能产生子节点或 link。默认输出 OK ID；--json 返回节点详情。

示例：
  rgraph set-conclusion 1 --text "当前提升尚不稳定，需要更多样本"
  rgraph set-conclusion 1 --file conclusion.md
"""),
    "set-code-dir": ("设置实验代码目录，检查用于复现实验的 README。", """目录必须存在；根部必须有 README 或 README.* 普通文件，大小写不敏感。
子目录中的 README 不计入，名为 README 的目录不计入。
缺失时报 readme_required（退出码 2），要求补全环境、运行步骤和结果
复现方式。只检查文件存在，不判断内容完整性；不复制代码、不执行实验。
路径支持 ~，相对当前工作目录解析，保存为绝对路径。
展开父节点时再次检查；普通查询不检查。默认输出 OK ID；--json 返回节点。

示例：
  rgraph set-code-dir 1 ./experiments/baseline
"""),
    "set-value": ("仅供用户人工评估节点价值；禁止 Agent 自行调用。", """仅供用户使用。禁止 Agent 自行调用本命令评分或调整评分。
VALUE 必须是 [0,1] 内的有限数，拒绝 NaN、无穷大和越界值（退出码 2）。
0 表示已评估且价值为零；未评估为 null，用 clear-value 恢复。
无需先填结论和目录；value 也不是展开父节点的必要条件。
子树值查询时计算，不可手动设置。默认输出 OK ID；--json 返回节点详情。

示例：
  rgraph set-value 2 0.8
"""),
    "clear-value": ("仅供用户清除价值评估；禁止 Agent 自行调用。", """仅供用户使用。禁止 Agent 自行调用本命令清除评分。
将节点价值恢复为未评估（null）。不删除节点，不修改结论、目录、文本或边。
未评估节点不参与祖先的子树均值，但仍遍历其后代。
默认输出 OK ID；--json 返回更新后的节点详情。

示例：
  rgraph clear-value 2
"""),
    "show": ("查看节点全文、结论、实验目录、价值统计和全部相邻边。", """默认展示文本详情，边包含 observation 和 action；目录不会重新校验。
--json 返回完整节点字段、subtree_value、descendant_count、
scored_descendant_count，以及 incoming/outgoing 边数组。
--text-only 仅原样输出 text，不额外添加换行，不能与 --json 同用。
未评估价值或没有已评估后代时显示 —，JSON 中为 null。

示例：
  rgraph show 2
  rgraph --json show 2
  rgraph show 2 --text-only > node.md
"""),
    "list": ("筛选并排序节点，查看价值和研究记录摘要。", """默认列出全部节点，按 ID 升序。多个筛选条件同时生效。
表格列：ID、VALUE、SUBTREE、SCORED/TOTAL、TEXT、CONCLUSION。
TEXT 和 CONCLUSION 为首个非空行摘要，最多 60 字符；完整内容用 show。
未设置结论显示“尚未形成结论”。
未评估价值排序时始终放最后；SCORED/TOTAL 为已评估后代数/后代总数。
--json 返回完整节点对象数组，包含结论、目录和价值统计，不含相邻边。

示例：
  rgraph list --unscored
  rgraph list --sort subtree-value --desc --limit 20
  rgraph --json list --roots
"""),
    "search": ("按区分大小写的字面子串搜索研究记录。", """nodes 搜索节点 text、conclusion；edges 搜索 observation、action。
不搜索实验路径；不解释正则、% 或 _。默认搜索所有节点和边。
默认显示匹配对象标识和文本；若匹配结论，用 show 查看完整节点详情。
--json 返回数组，type 为 node 或 edge，附完整原始字段，无价值统计。
没有匹配项也成功返回（JSON 为 []）。

示例：
  rgraph search "对照组"
  rgraph --json search "样本不足" --in edges
"""),
    "tree": ("将研究 DAG 按树形缩进展开，显示边的观测与动作。", """省略 ID 时从全部根节点展开；指定 ID 时只展开该节点及后续。
根和子节点按 ID 升序，树枝直接连接节点，入边的观察和行动显示在子节点下方。
默认显示文本、观察、行动和结论的首个非空行摘要（最多 60 字符），
多行内容标注剩余行数；未设置结论时显示“尚未形成结论”。
--full 展开节点文本、观察、行动和结论全文，保留段落换行。
长行按终端宽度折行，续行保留树线和缩进；未赋值的价值字段隐藏。
共享节点首次出现时展开，后续显示 [ID] ↩ 和入边信息，不再展开节点详情。
深度以边数计算，起点为 0；--depth 0 只显示起点，不指定则完整展开。
共享节点的深度限制按首次遇到的路径应用。
subtree 是全部已评估可达后代的平均价值，不含自身、共享后代去重，
未评估节点不参与均值但仍遍历其后代；无已评估后代时隐藏该值（JSON null）。
显示深度不影响价值计算。终端不展示实验目录，详情用 show。
--json 返回 roots（起点 ID）、nodes（完整节点及价值统计）、edges；
共享节点去重，由多条边引用；不使用 ↩ 字符。

输出示意：
  [1] 基线研究
  │   value=0.4  subtree=0.8
  │   结论：当前结果需要更多样本验证
  │
  └── [2] 扩样实验
      value=0.8
      观察：样本不足
      行动：扩大样本
      结论：扩大样本后效果仍然稳定

示例：
  rgraph tree
  rgraph tree 1 --depth 2
  rgraph tree 2 --full
  rgraph --json tree 1
"""),
    "link": ("在两个已有节点之间创建带观测和动作的有向边。", """方向为 PARENT -> CHILD；父节点必须有结论和有效实验目录/根部 README。
observation 是导致改进的观测原因，action 是下一步做什么，两项必填且非空。
不创建节点；用于补充入边、组合分支。禁止自连接、重复边或形成环（退出码 4）。
已存在的边用 edge edit 修改。默认输出 OK PARENT -> CHILD；--json 返回边。

示例：
  rgraph link 3 4 --observation "参数变化影响结果" --action "纳入组合实验"
"""),
    "unlink": ("移除一条已有边，保留两端节点及所有其他连接。", """不会删除或递归修改节点，允许产生断开的分支或新根节点。
边不存在返回 edge_not_found（退出码 3）；不要求父节点字段完整。
默认输出 OK PARENT -> CHILD；--json 返回 parent_id、child_id。

示例：
  rgraph unlink 3 4
"""),
    "edge": ("通过父子节点 ID 查看、替换或追加边的两个文本字段。", """每条边由 PARENT -> CHILD 唯一标识，字段为 observation（观测原因）与
 action（后续动作）。创建边用 link 或 add --parent。
show 显示整条边；edit 替换指定字段；append 向指定字段追加换行和文本。
edit/append 至少指定一个字段，内容不可为空白，未指定字段保持原值。
修改现有边不要求父节点已补齐结论/目录；不接受 --text/--file。

示例：
  rgraph edge show 1 2
  rgraph edge edit 1 2 --action "扩大样本，并增加对照组"
  rgraph edge append 1 2 --observation "重复实验也有相同现象"
  rgraph edge edit --help
"""),
    "rm": ("删除没有任何入边和出边的节点。", """有连接时返回 node_connected（退出码 4），请先逐条 unlink。
不递归删除，不复用被删除的 ID。默认输出 OK ID；--json 返回 {"id": ID}。

示例：
  rgraph rm 5
"""),
    "export": ("将整张图的原始数据以 JSON 输出到标准输出。", """始终输出 JSON，无需 --json。顶层为 schema_version、nodes、edges。
包括完整文本、结论、实验目录、价值、边的 observation/action 和时间；
不包含可重新计算的子树统计，不导出实验代码目录中的文件。
当前无导入/跨库合并命令；完整数据库备份可在无写入时复制 SQLite 文件。

示例：
  rgraph export > research.json
  rgraph --db another.db export > another.json
"""),
}

EDGE_COMMANDS = {
    "show": ("查看已有边的观测原因、后续动作和时间。", """边由 PARENT -> CHILD 唯一标识。--json 返回 parent_id、child_id、
observation、action、created_at、updated_at。不检查父节点实验目录。
边不存在返回 edge_not_found（退出码 3）。

示例：
  rgraph edge show 1 2
  rgraph --json edge show 1 2
"""),
    "edit": ("替换已有边的 observation 和/或 action 字段。", """至少指定 --observation 或 --action；拒绝空白值，未指定的字段保持原值。
不改变连接关系，不要求父节点字段完整，不接受 --text/--file。
默认输出 OK PARENT -> CHILD；--json 返回更新后的整条边。

示例：
  rgraph edge edit 1 2 --action "扩大样本，并增加对照组"
  rgraph edge edit 1 2 --observation "发现排序问题" --action "调整排序"
"""),
    "append": ("向已有边的 observation 和/或 action 追加内容。", """至少指定一个字段；拒绝空白值。对指定字段追加一个换行及新文本，
未指定字段保持原值。不要求父节点字段完整，不接受 --text/--file。
默认输出 OK PARENT -> CHILD；--json 返回更新后的整条边。

示例：
  rgraph edge append 1 2 --observation "重复实验也出现相同现象"
  rgraph edge append 1 2 --action "补充一次独立复现"
"""),
}
