# X0 Historical Evidence Owner Decision

- Verdict: `blocked_pending_owner_adjudication`
- Protected tracked deletions: `197`
- Current-authority conflict: `True`
- Mutation performed by X0: `0`

| Collection | Owner | Deleted | Exact path refs | Collection refs | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| `experiments/full_architecture_context_observation` | `context_evaluation_original_experiment_owners` | 108 | 6 | 427 | `needs_owner_decision` |
| `experiments/metadata_architecture` | `metadata_experiment_owner` | 15 | 0 | 1 | `needs_owner_decision` |
| `experiments/mini_swe_active_iteration` | `active_iteration_experiment_owner` | 74 | 3 | 13 | `needs_owner_decision` |

## Required owner decision

逐路径明细见 `deletion_adjudication.json`。用户/owner 必须明确选择 `restore_from_head`、`retain_intentional_deletion_pending_H4` 或 `replaced_by_new_collection`；在此之前 package release 保持阻塞。

X0 不执行 restore/delete/stage，也不把当前 dirty HEAD 批准为 B1。
