"""A fixed camera in the same queue: a laptop posts JPEG frames to POST /cam/<id>/frame; the API writes the frame under
<repo>/cams/ (WTDD_CAMS redirects it; the tests set a temp dir), runs the existing detector in its own process
(python -m wtdd.watch --source <frame> --once --out <boxed>; cv2 never loads in the API process), writes one cam.frame
and one cam.detect row, publishes <id>.json for the remote (GET /cam, GET /cam/<id>/frame.jpg), and a person box while
the intruder watch is armed (<repo>/intruder.on, the same gate as the dog's feed) raises the same who-dis path a stop
raises (intruder_alarm with file=<the frame>, pending.json, one gated post), at most once per COOLDOWN_S per camera.
The contract is wtdd/cam/test_cam.py; this module is built on feat/09-fixed-cam. Nothing here has met a real laptop yet."""
