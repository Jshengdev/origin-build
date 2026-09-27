"""Watch one data-channel topic of the dog for N seconds and write what it publishes as one dog.sniff row.

The row (wtdd/dog/body.py sniff): messages, hz, keys (a key tree with types and array lengths), first_payload (cut to
2 KB), last_at; ok=false with "0 messages in N s" when nothing arrived, and on a utlidar topic args.why names the driver's
voxel-decoder trap. The three topics Body owns (rt/lf/sportmodestate, rt/utlidar/voxel_map_compressed,
rt/utlidar/robot_pose) are tapped from Body's own callbacks and never re-subscribed; any other RTC_TOPIC is subscribed
for the window only; any other name is refused before any send (and before any connect). GET /dog/streams and the
admin page's Streams table show every sniffed topic.
  python -m wtdd sniff topic=rt/lf/lowstate seconds=5      (with the API up, it runs in the API's dog session)
UNVERIFIED on the dog: every topic but rt/lf/sportmodestate. Needs the dog, in this order: rt/lf/sportmodestate (the
known shape proves the tool), rt/lf/lowstate, rt/multiplestate, rt/sportmodestate, rt/utlidar/robot_pose (LiDAR on),
rt/utlidar/lidar_state (expect the decoder-trap row).
"""
ARGS = {"topic": {"type": "string", "doc": "an RTC_TOPIC name (rt/lf/lowstate) or key (LOW_STATE)"},
        "seconds": {"type": "number", "default": 5, "doc": "how long to watch, at most 60"}}


def run(topic, seconds=5):
    from ..commands import _via_api
    via = _via_api("sniff", topic=topic, seconds=seconds)   # the API process owns the dog's one WebRTC slot
    if via is not None:
        return via
    from ..dog.session import DogSession
    return DogSession.get().sniff(topic, seconds)
