# 09-3 · a trailing comment in .gitignore disables the pattern

**Symptom.** With the line `cams/   # 09: a fixed camera frames and detections (wtdd/cam)` added to `.gitignore`,
`git check-ignore -v cams/probe.jpg` printed nothing and exited 1, and `git status --short cams/` showed `?? cams/`.
The runtime frames would have been offered for commit.

**Root cause.** gitignore treats `#` as a comment only at the start of a line. After a pattern, `# ...` is part of the
pattern, so the line matched a path literally named `cams/   # 09: ...`, never `cams/`. Every item appending to the
runtime-state list (01's ui/grid.json, 09's cams/) can fall into this.

**Fix (verbatim, .gitignore, under the runtime-state list).**
```
# 09 · fixed-cam: a fixed camera's frames and detections (wtdd/cam; WTDD_CAMS moves it)
cams/
```

**Verify.** `git check-ignore -v cams/probe.jpg` prints `.gitignore:45:cams/	cams/probe.jpg` and exits 0.
