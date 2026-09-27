# 20-1 · the detector's weights are AGPL-3.0, not Apache-2.0

**Symptom.** `wtdd/watch.py`'s docstring opened with "an open-source detector (ultralytics YOLO11n, COCO's 80 classes,
Apache-2.0 weights)". That is a licence claim in the shipped record, and it is false.

**Root cause.** Nobody read the licence when the detector went in. The package the weights come from says otherwise:
`.venv/lib/python3.13/site-packages/ultralytics-8.4.163.dist-info/METADATA` line 7 reads `License: AGPL-3.0`, and
Ultralytics' licence page (https://www.ultralytics.com/license) puts its trained YOLO models under AGPL-3.0 by default,
with an Enterprise licence for closed products. yolo11n.pt is one of those models. A public hackathon repo can use it
under AGPL-3.0; the docstring still has to say so.

**Fix (verbatim, the first two lines of `wtdd/watch.py`'s docstring).**
```
"""The eye's second opinion: an open-source detector (ultralytics YOLO11n, COCO's 80 classes, AGPL-3.0 weights: ultralytics'
licence, https://www.ultralytics.com/license; the venv's ultralytics-8.4.163 METADATA says License: AGPL-3.0) in
```
No `Apache-2.0` remains anywhere in the docstring.

**Verify.**
```
grep -n '^License' .venv/lib/python3.13/site-packages/ultralytics-8.4.163.dist-info/METADATA   # 7:License: AGPL-3.0
/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.test_vocab.Watch        # test_docstring_names_the_real_licence ok
```
