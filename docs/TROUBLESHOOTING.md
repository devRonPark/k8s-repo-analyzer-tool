# Troubleshooting & environment notes

## This folder's mount blocks file deletion

The project folder is a mount that allows **create / write / rename** but
**blocks delete (`unlink`)**. `rm` and any delete fail with
`Operation not permitted`. Rename (`mv`) and overwrite work fine.

## `git commit` fails with a stale `index.lock`

**Symptom**

```
fatal: Unable to create '.git/index.lock': File exists.
Another git process seems to be running in this repository...
```

A prior git operation left stale lockfiles under `.git`, and the mount won't let
git (or `rm`) delete them. `git commit` touches **several** locks in sequence, so
you may hit them one at a time: `.git/index.lock`, then `.git/HEAD.lock`, then
`.git/refs/heads/<branch>.lock`.

**Do NOT** try `rm -f` on them — delete fails on this mount.

**Fix — rename every stale `.git` lock aside, then commit:**

```bash
cd <project>           # bash path: /sessions/<session>/mnt/k8s-repo-analyze-agent
# Move ALL known git locks aside in one go (rename works even though delete doesn't)
for lock in .git/index.lock .git/HEAD.lock .git/refs/heads/*.lock; do
  [ -f "$lock" ] && mv "$lock" "$lock.stale.$$"
done
git commit -m "..."    # git's own lockfiles use create+rename -> succeeds
```

If a lock reappears mid-command, just rerun the loop + commit; each stale lock
only needs to be moved aside once.

**Notes**

- Ignore noisy `warning: unable to unlink ... tmp_obj_*` / `index.lock` messages
  during `git add`/`commit` — non-fatal cleanup failures; objects/commit are still
  written. Filter with `| grep -vi "unable to unlink"`.
- Leftover `.git/index.lock.stale` and stray scratch files can't be deleted from
  here; harmless, remove manually outside the sandbox if desired.
- Prefer git steps that create-or-rename rather than delete.
