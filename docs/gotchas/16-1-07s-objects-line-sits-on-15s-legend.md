# 16-1 · 07's objects line and 15's floor plan legend are drawn on the same baseline

**Symptom.** On the first branch that holds both 07 (objects) and 15 (floor plan), the map's top-left corner reads as
two lines printed on top of each other: `objects 0 · 0 windows · session · WTDD_CAM_FOV_DEG is required: ...` runs
through `walls · 2 runs · furniture · 634 cells · tall · 36 · ...`, and neither can be read (headless on :7923, the
furnished fixture planted, item 16's first screenshot).

**Root cause.** Each item placed its map legend in the free margin above the house (ui/house.svg's rooms start at
y = 50, 15-3) without seeing the other: 07's ObjectsLayer draws `<text class="lbl objlbl" x="12" y="48">` and 15's
FloorPlanLayer draws `<text class="lbl fplbl" x="12" y="52">`, 4 px apart at a 17 px font. ObjectsLayer mounts after
FloorPlanLayer, so its line paints over 15's. The two first meet in the keep-both merge of origin/feat/07-objects into
item 16's branch (f6a7677); neither branch alone shows it.

**Fix (verbatim).** Only 07's y moves, in ui/index.html's ObjectsLayer, below 15's legend lines (52, 76, 100 when a
reason shows) and 16's (124, 148 when a reason shows):

```
    <text class="lbl objlbl" x="12" y="172">objects ${o ? all.length : "…"}
```

(was `y="48"`). The line keeps 07's `.lbl` halo; it now sits over the house's rooms, whose vertical walls cross it
between words, which is the lesser harm. Any later layer that adds a map legend line takes the next free 24 px step
(196, ...) or a text-sized box like 15-5's.

**Verify.** docs/evidence/night-2/16-remote.png: the grid line (y 28), the floor plan's two lines, the blobs line and
the objects line each read whole, top to bottom, none overlapping. In the DOM, `text.objlbl` in the legend has y 172.
