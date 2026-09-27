# 22-7 · a restored file ran the mutant's bytecode

**Symptom.** To see the new `between` test fail, the comparison in `_Check.row()` was mutated three ways (`<`, `>=`, and the
two indices swapped). The test ran against each mutant, and the file was restored with `cp` after each run. `cmp` said
the source was byte for byte the original. Even so, the next run of the test failed on the original code with
`'PASS' != 'UNSAFE'`, which is the swapped mutant's result.

**Root cause.** A `.pyc` is trusted when the source's mtime, in whole seconds, and its size both match the values stored
in its header. The swap mutant is the same size as the original. The `cp` that restored the file landed in the same
second as the mutant's run. So `wtdd/livecheck/__pycache__/__init__.cpython-313.pyc` still held the mutant, with header
`(1790471180, 22256)`, and the restored source had the same mtime and size.

**Fix (verbatim).**

```
rm -rf wtdd/livecheck/__pycache__
```

Run this after restoring a mutated file, before the run that is meant to be green. Or run the mutants with
`PYTHONDONTWRITEBYTECODE=1`.

**Verify.** `.venv/bin/python -m unittest wtdd.livecheck.test_livecheck.Rows.test_between_a_tool_after_a_and_before_b_is_unsafe`
is OK on the original code. The three mutant runs are in `/tmp/night2/22/fix3/between-mutations.txt`.

Rule: after a mutation test, clear the package's `__pycache__` before trusting a green run. `cmp` checks the source, not
the bytecode Python will actually run.
