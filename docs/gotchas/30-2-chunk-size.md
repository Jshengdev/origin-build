# 30-2 · the upload's block size is 4096 characters, not the module's CHUNK_SIZE

**Symptom.** Two inventories of the driver disagreed: one read the AudioHub upload block as 61440 characters, the other as 4096.

**Root cause.** `unitree_webrtc_connect/webrtc_audiohub.py:13` defines `CHUNK_SIZE = 61440` at module level, and nothing in the file uses it. `upload_audio_file` (`:120-187`) sets its own `chunk_size = 4096` at `:148`, then slices the base64 text with that value. The megaphone upload at `:234` also uses 4096. Reading only the top of the file gives the wrong number.

**Fix (verbatim).** `wtdd/dog/audio.py` uses the upload's own value and cites the line:

```python
CHUNK = 4096          # base64 characters per upload block: webrtc_audiohub.py:148
CHUNK_GAP_S = 0.1     # between blocks: webrtc_audiohub.py:180
```

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_audio.Driver.test_chunk_size_is_the_drivers_own_upload_line -v` passes. It reads the driver's text from `async def upload_audio_file` on, without importing it, and compares `chunk_size = (\d+)` with `audio.CHUNK`. `wtdd.dog.test_audio.Upload` then checks the 1 s fixture as 29 blocks of 4096 characters (the last one shorter).

The first live upload (Needs the dog 30.1) is still the proof that the dog accepts this size. It must return code 0 for every block.
