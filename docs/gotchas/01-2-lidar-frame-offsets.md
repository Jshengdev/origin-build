# 01-2 · a LiDAR frame's json starts at byte 12 of the wire buffer, not byte 8

**Symptom.** A synthetic voxel frame built from lidar.py's old docstring ("uint32 json length at byte 4, json at
[8:8+len], LZ4 block after") fails inside the driver before any wtdd code runs:
`JSONDecodeError: Expecting value: line 1 column 1 (char 0)` raised at
`unitree_webrtc_connect/webrtc_datachannel.py:158`, called from `:129`.

**Root cause.** The driver reads the frame in two steps. `deal_array_buffer` (webrtc_datachannel.py:126-131) checks
the first two uint16 for (2, 0) and slices those 4 bytes off; `deal_array_buffer_for_lidar` (:153-156) then reads the
uint32 json length at byte 0 and the json at byte 8 of the sliced buffer. In the wire buffer that is: type header at
0-3, json length at 4-7, four bytes at 8-11 the driver never reads, json at 12. The docstring's offsets were relative
to the sliced buffer but written as if they were the wire buffer's. What the dog puts in bytes 8-11 is UNVERIFIED
(the fixture writes the LZ4 block length there; the driver ignores it either way).

**Fix (verbatim).** The fixture's layout, wtdd/dog/fixtures/make_voxel_frames.py `frame_bytes()`:

```
    return struct.pack("<HH", 2, 0) + struct.pack("<I", len(j)) + struct.pack("<I", len(block)) + j + block
```

and lidar.py's docstring now reads: "in the wire buffer the uint32 json length is at byte 4, four bytes at 8-11 the
driver skips (content UNVERIFIED), the json at [12:12+len], the LZ4 block after (:153-156 read the length at 0 and the
json at 8 of the sliced buffer)".

**Verify.** `python -m wtdd.dog.fixtures.make_voxel_frames` decodes all three fixture frames back through the driver
(one line per frame with its voxel count). Measured tonight, through the driver's own `deal_array_buffer`: the
json-at-8 layout raises the JSONDecodeError above; the `frame_bytes(0)` layout decodes `voxels=3312 frame_id=odom
origin=[-3.2, -3.2, -0.3]`.
