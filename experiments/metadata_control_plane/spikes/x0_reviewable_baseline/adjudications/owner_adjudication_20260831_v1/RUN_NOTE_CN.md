# X0 Owner Adjudication Run Note

- Decision: `restore_from_head`
- Source run: `runs/x0_20260831_v4`
- Source commit: `2b9a0f0fb40a43a89633bee1ab6db92273777100`
- Restored tracked paths: `197`
- Remaining tracked deletions: `0`
- Previously observed untracked paths preserved: `193`
- Collisions / staging mutations / new deletions: `0 / 0 / 0`

本裁决仅恢复 immutable inventory 中的精确 tracked paths，不覆盖同目录新实验文件，也不把
当前 dirty worktree 纳入 B1。B1 的独立 commit pin 见 `../../b1_baseline.json`。
