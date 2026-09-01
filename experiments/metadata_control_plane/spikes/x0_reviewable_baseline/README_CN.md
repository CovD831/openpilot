# X0 Reviewable Baseline 与历史证据保护

> Status: Active engineering spike
> Authority: Read-only baseline and deletion-adjudication evidence; not deletion authority
> Owner: Architecture / documentation / experiment owners
> Supersedes: None
> Last reviewed: 2026-08-31

## 1. 目的

X0 在任何架构包提交或生产重构前，生成当前 worktree 的可复现基线：

- Git branch/HEAD 和 dirty status；
- tracked modified/deleted/untracked 路径；
- `Code/src` 修改的模块 owner；
- 受保护历史实验集合中的 tracked deletions；
- 当前工作树中对删除路径/集合的引用；
- 每个删除项的 owner 和待裁决动作。
- owner-reviewed B1 Git commit pin；当前 dirty worktree 明确排除。

X0 runner 不恢复、不删除、不暂存文件，也不把当前 HEAD 自动批准为 B1。它只读取
`b1_baseline.json` 中经过 owner review 的 commit pin，并在 `--check` 模式下对受保护删除或
缺失 B1 pin fail closed。

## 2. 运行

```bash
python3 experiments/metadata_control_plane/spikes/x0_reviewable_baseline/runner.py \
  --output experiments/metadata_control_plane/spikes/x0_reviewable_baseline/runs/x0_20260831_v1
```

保护门：

```bash
python3 experiments/metadata_control_plane/spikes/x0_reviewable_baseline/runner.py --check
```

只要存在受保护 tracked deletion，或缺少有效 B1 commit pin，`--check` 返回非零。它不执行
`git restore`、`git checkout`、`git add` 或任何删除命令。

## 3. 裁决状态

每个删除项只能由对应 owner/用户裁决为：

```text
restore_from_head
retain_intentional_deletion_pending_H4
replaced_by_new_collection
needs_owner_decision
```

X0 首次运行一律使用 `needs_owner_decision`。未来的裁决文件必须单独审查；不能通过修改
runner 默认值批量批准删除。

2026-08-31 owner 裁决选择 `restore_from_head`，结果记录在
[`adjudications/owner_adjudication_20260831_v1/`](adjudications/owner_adjudication_20260831_v1/RUN_NOTE_CN.md)：
197 个 tracked paths 已恢复，0 个 tracked deletion 剩余，193 个已观察到的 untracked paths
全部保留。

## 4. B1 commit pin

当前 B1 由 [`b1_baseline.json`](b1_baseline.json) 固定到一个完整 Git commit identity。B1
比较必须使用该 commit 的 clean checkout/worktree；当前工作树的修改和未跟踪文件不属于
B1。更新 B1 必须使用新 baseline ID、重新 owner review，并保留旧 X0 run。

当前 canonical post-adjudication snapshot 是
[`runs/x0_20260831_v6/`](runs/x0_20260831_v6/RUN_NOTE_CN.md)；v1–v5 保留为不可覆盖的过程证据。

## 5. 输出

```text
runs/<immutable_run_id>/
├── preflight.json
├── inventory.json
├── deletion_adjudication.json
├── analysis.json
├── OWNER_DECISION_CN.md
└── RUN_NOTE_CN.md
```

输出目录不可覆盖。文件仅记录路径、Git 状态、owner、引用位置和计数，不复制实验正文、
凭据或 raw provider output。
