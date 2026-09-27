# 06-1 · pathfinding's Grid.node() takes a negative index and wraps to the far edge

**Symptom.** A point left of or above the map's viewBox (a dog pose that has drifted off the drawn house, or a typed
`from=-5,900`) does not fail. `int(-5) // CELL` is `-1`, and `Grid.node(-1, 90)` returns the node at column 105, on the
map's far right edge. On the drawn rooms that node is usually eroded, so the error names the wrong place ("start is
not on walkable floor"). On the grid cost map, where floor the LiDAR never saw is walkable, the node is free and A*
plans a route from the opposite side of the map with nothing in the row to show it.

**Root cause.** python-pathfinding 1.0.22 `Grid.node(x, y)` is `return self.nodes[y][x]`, plain list indexing with no
bounds check (`Grid.inside()` exists but `node()` does not call it). Python lists accept negative indices, so an
off-map point below zero wraps instead of raising. A point past the right or bottom edge raises IndexError, which
does fail but names no point.

**Fix (verbatim).** wtdd/plan.py `_route()`, which plan() and replan() both call, checks both ends before building
the nodes:

```
    for q, name in ((a, "start"), (b, "end")):
        if not (0 <= q[0] < W and 0 <= q[1] < H):
            raise ValueError(f"{name} {[round(v) for v in q]} is off the map (0..{W} x 0..{H} px)")
```

`_at()` (occupied() and replan's rejoin search) returns False off the map for the same reason, and never indexes a
negative cell.

**Verify.**

```
$ python -c "from pathfinding.core.grid import Grid; g = Grid(matrix=[[1] * 106 for _ in range(154)]); n = g.node(-5 // 10, 900 // 10); print((n.x, n.y), n.walkable)"
(105, 90) True
$ cp wtdd/fixtures/grid_wall.json ui/grid.json && python -m wtdd plan_path from=-5,900 to=300,900; rm ui/grid.json
[wtdd:plan] plan.route ok=False app=map ms=3 err=ValueError: start [-5, 900] is off the map (0..1060 x 0..1540 px)
error: ValueError: start [-5, 900] is off the map (0..1060 x 0..1540 px)
```
