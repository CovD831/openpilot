# Skill 标准调研与 op0 接入设计（2026-09-10）

> 调研对象：Anthropic Agent Skills 开放标准（2025-12-18 发布）、Claude Code 实现、API 侧容器化实现。
> 结论先行：**Agent Skills 已是跨厂商开放标准，op0 直接实现该标准 = 免费获得整个生态的现成 skills**。

## 一、标准格式（比"只有一个 SKILL.md"丰富得多）

```
skill-name/
├── SKILL.md            # 必需：YAML frontmatter + Markdown 指令
├── scripts/            # 可选：可执行代码（Python/Bash）
├── references/         # 可选：参考文档（按需加载的详细说明）
└── assets/             # 可选：资源文件（模板/字体/boilerplate）
```

SKILL.md frontmatter（YAML）：

| 字段 | 必需 | 约束 | 作用 |
|---|---|---|---|
| `name` | 是 | ≤64 字符，小写连字符 | 技能名 / `/name` 调用名 |
| `description` | 是 | ≤200 字符 | **触发机制**：agent 靠它判断何时自动加载 |
| `disable-model-invocation` | 否（cc 扩展） | bool | true = 只许用户 `/调用`，禁止自动触发（部署类危险操作用） |
| `context: fork` | 否（cc 扩展） | — | 在 subagent 中执行（隔离上下文） |
| `allowed-tools` | 否（cc 扩展） | 列表 | 限制该 skill 可用的工具 |
| `dependencies` | 否 | 如 `python>=3.8` | 环境依赖声明 |

body 里 cc 还支持**动态上下文注入**：`` !`git diff HEAD` `` 行在 Claude 看到内容前被执行替换——skill 内容随工作树实时生成。

## 二、核心机制：三层渐进式披露（progressive disclosure）

这是整个标准最值得抄的设计，直接回应"system prompt 长度是能力-成本权衡"：

1. **元数据层**：启动时只有 name + description 进 system prompt（每个 skill 几十 token）；
2. **body 层**：agent 判断相关后才读 SKILL.md 全文；
3. **文件层**：需要时再读 scripts/references/assets 里的具体文件。

→ 装了 100 个 skill，未触发时上下文成本 ≈ 100 × 一行索引。能力上下文**按需增长**，无任务不背无关技能的成本。cc 官方说法："长参考材料在需要之前几乎不花费任何成本"。

scripts/ 的价值：确定性操作（排序、PDF 处理、格式校验）用代码执行而非 token 生成——省 token 且结果可重复。代码不进上下文，Claude 只执行。

## 三、cc 怎么接入（机制细节）

- **位置层级**（同名覆盖，高优先）：企业托管 > 个人 `~/.claude/skills/` > 项目 `.claude/skills/` > plugin `<plugin>/skills/`（plugin 用 `name:skill` 命名空间，不冲突）；
- **调用**：`/skill-name` 显式调用 + description 匹配自动触发（`disable-model-invocation: true` 可关自动）；
- **实时变更检测**：监视 skills 目录，增删改即时生效（新顶级目录需重启）；
- **升级为 plugin**：skill 目录加 `.claude-plugin/plugin.json` 即可捆绑 agents/hooks/MCP——skill 是插件生态的最小单元；
- **与 commands 合流**：旧 `.claude/commands/*.md` 自动视为 skill（同名时 skill 优先）；
- **API 侧**（另一形态）：skill 上传到 Anthropic 服务端，容器参数挂载（≤8 个/请求），在代码执行环境里跑——云端形态，op0 不需要。

## 四、op0 接入设计（对齐标准，最小实现）

- **目录**：项目级 `.openpilot/skills/<name>/SKILL.md` + 用户级 `~/.openpilot/skills/`（同名项目覆盖用户——注意与 cc 相反：项目特定知识应更精确，取 cc 的"个人覆盖项目"还是反转？建议**项目覆盖用户**，理由：项目内约定 > 个人通用习惯）；
- **注入**：契约不变头部追加一段 skill 索引（每 skill 一行 `name: description`），compaction 投影的不变头部同步携带——索引是治理契约的一部分，永不被折叠；
- **加载**：模型用 `openpilot_read` 读 SKILL.md 正文（已有工具，零新增）；scripts 用 `openpilot_bash` 执行（沙箱内！skill 代码默认进沙箱——三层披露 + 物理墙天然组合）；
- **调用**：body 首部约定即可（无 /命令机制——op0 的 UI 入口后续再加，第一版靠 description 自动触发 + 用户说"用 xx skill"）；
- **安装**：放目录即装（目录监视可后置）；`/skill list` 只读展示；
- **不改的东西**：admission/receipt/closure 全部照旧——skill 只是上下文装载机制，不碰治理语义；skill 的 bash 执行走沙箱 = 物理墙对第三方代码同样生效。

## 五、与 subagent 的会合点

cc 的 `context: fork` 证明 skill 与 subagent 天然组合：skill 声明自己该在隔离子代理里跑。op0 的 subagent（receipt 链式执行域）落地后，skill 的 fork 语义直接映射为"在子执行域里装载该 skill"。这也是 subagent 排在最后的另一个理由：skill 设计要给 fork 留字段，实现时预留。

## 六、实施清单（沙箱完成后）

T1 skills 目录发现与索引生成（~30 行）→ T2 契约/投影注入（~15 行）→ T3 `/skill` 展示（~15 行）→ T4 冒烟（装一个真实 skill 验证自动触发 + 正文加载 + 脚本沙箱执行）。预算估 +70 行 → 3620。
