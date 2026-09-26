# 21-1 · the stops arg needs quotes: `;` ends a shell command

**Symptom.** Goal 21's verifying CLI as written, `python -m wtdd plan_route stops=448,455;436,586;520,600`, runs the
tool with one stop and then zsh tries to run the other two stops as commands (run from a zsh script, hence the
script's name on the last lines; an interactive zsh prints `zsh: command not found: 436,586`):

```
[wtdd:plan] route start start=first tap at=[448, 455] taps=1 grid=ui/grid.json
[wtdd:plan] plan.multistop ok=False app=map ms=0 err=ValueError: a route needs a start and at least one stop (got 1 point(s))
error: ValueError: a route needs a start and at least one stop (got 1 point(s))
/tmp/night1/21/unquoted.zsh:5: command not found: 436,586
/tmp/night1/21/unquoted.zsh:5: command not found: 520,600
exit=127
```

The tool fails loud and writes a plan.multistop row with ok false, but the route the command meant was never asked for.

**Root cause.** `;` separates commands in zsh and bash, so the shell cuts the line at each `;` before Python sees it.
`stops=448,455` is the tool's whole argument; `436,586` and `520,600` are two more commands.

**Fix (verbatim).** Quote the arg:

```
python -m wtdd plan_route "stops=448,455;436,586;520,600"
```

The tool's docstring, its `stops` arg doc ("quote it in a shell") and wtdd/plan.py's docstring show the quoted form.
POST /tools/plan_route (the page) sends a JSON string, so there is nothing to quote there.

**Verify.** The quoted pair prints 2 legs:

```
$ cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_route "stops=448,455;436,586;520,600"; rm ui/grid.json
[wtdd:plan] route start start=first tap at=[448, 455] taps=3 grid=ui/grid.json
...
[wtdd:plan] plan.multistop ok=True app=map ms=28 err=
[wtdd:plan] multistop route planned legs=2 stops=2 waypoints=6 length_m=2.15 cost_map=grid source=ui/grid.json
```

stdout is the JSON result with `"legs"` of length 2 and `"stops": [2, 5]`.
