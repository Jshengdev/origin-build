# 16-2 · a shelf labelled shelf goes grey only in front: its back three columns stay the wall's

**Symptom.** On goal 15's furnished room, a shelf label at p 0.91 greys 120 of the shelf's 240 cells. The front half
turns slab and the back half, against wall_a, stays ink. On the remote the shelf reads as a grey band beside a black
band (docs/evidence/night-2/16-remote.png, wall cells 418 to 298), not as one grey block.

**Root cause.** 15's `_runs` takes wall_a first (the longest run) and marks every grounded cell within THICK (0.15 m,
3 cells) of its line, inside its extent, as wall_a's thickness. The shelf stands flush against wall_a (x 1.7 to 2.0 m,
wall at 2.0 m), so its columns at gx 37, 38 and 39 belong to wall_a's run before the shelf's own run is found. The
shelf's run then holds gx 34 to 37: gx 37 is in both runs. erase() greys only an erased run's cells that no kept run
also holds, so gx 37 to 39 stay wall_a's. The LiDAR cannot tell a shelf's back from the wall it stands against, and a
label may not decide it for the geometry.

**Fix (verbatim).** None to the rule: it is the law ("a label never adds a cell, a line, or opens a gap") applied to a
cell two runs share. wtdd/dog/blobs.py erase():

```
    gone = [k for k, run in enumerate(runs) if any(len(run & s) * 2 > len(run) for s in named)]
    kept = set().union(*(run for k, run in enumerate(runs) if k not in gone))
    cls = plan["cls"].copy()
    for a, b in set().union(*(runs[k] for k in gone)) - kept:
        if cls[b, a] == 1:
            cls[b, a] = 3
```

The test grades the shelf as "at least half of its cells grey, and every changed cell is a shelf cell", never as all
240. Growing THICK or ordering the runs differently would move the line of the wall the planner avoids. That belongs
to 15's constants on live frames, never to a label.

**Verify.** `python -m unittest wtdd.dog.test_blobs`: Erase.test_a_shelf_label_moves_the_shelf_off_the_wall_layer_and_both_walls_stay
(every wall_a and wall_b cell still class 1, 120 >= 240 // 2 grey) and
Serve.test_the_press_labels_what_is_in_view_and_the_floor_plan_greys_the_shelf (slab grows by exactly the wall cells
lost). On the fixture, `floorplan._plan(...)["runs"]` shows run 0 (wall_a) over gx 37 to 40 and run 2 (the shelf) over
gx 34 to 37.
