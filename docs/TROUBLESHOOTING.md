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

A prior git operation left a stale `.git/index.lock`, and the mount won't let git
(or `rm`) delete it.

**Do NOT** try `rm -f .git/index.lock` — it fails on this mount.

**Fix — rename the lock aside, then commit:**

```bash
cd <project>           # bash path: /sessions/<session>/mnt/k8s-repo-analyze-agent
mv .git/index.lock .git/index.lock.stale   # rename works even though delete doesn't
git commit -m "..."                        # git's own lockfiles use rename -> succeeds
```

**Notes**

- Ignore noisy `warning: unable to unlink ... tmp_obj_*` / `index.lock` messages
  during `git add`/`commit` — non-fatal cleanup failures; objects/commit are still
  written. Filter with `| grep -vi "unable to unlink"`.
- Leftover `.git/index.lock.stale` and stray scratch files can't be deleted from
  here; harmless, remove manually outside the sandbox if desired.
- Prefer git steps that create-or-rename rather than delete.
