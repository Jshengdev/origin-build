# 30-1 · the driver's AudioHub class cannot be imported on Python 3.13

**Symptom.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -c "from unitree_webrtc_connect.webrtc_audiohub import WebRTCAudioHub"` ends with:

```
  File ".../site-packages/pydub/utils.py", line 16, in <module>
    import pyaudioop as audioop
ModuleNotFoundError: No module named 'pyaudioop'
```

**Root cause.** `unitree_webrtc_connect/webrtc_audiohub.py:8` imports `from pydub import AudioSegment` at module level. pydub 0.25.1 imports `audioop`, which Python 3.13 removed, then falls back to `pyaudioop`, which is not installed. pydub is only used there to turn an MP3 into a WAV; every AudioHub method is one `pub_sub.publish_request_new` on `rt/api/audiohub/request`.

**Fix (verbatim).** Do not import the module and add no dependency (no `audioop-lts`). `wtdd/dog/audio.py` sends the same requests through `Body._request`, which already times each one and reads its status code:

```python
from unitree_webrtc_connect.constants import AUDIO_API, RTC_TOPIC
...
async def request(body, topic: str, api_id: int, parameter: Any = None) -> tuple[int, dict]:
    """Body._request behind ALLOW: an id outside it raises PermissionError before anything is sent."""
    if api_id not in ALLOW.get(topic, ()):
        raise PermissionError(f"{topic} api_id={api_id} is not in audio.ALLOW")
    return await body._request(topic, api_id, parameter)
```

The WAV is made on this Mac by `/usr/bin/say` and ffmpeg (`render`), so the MP3 step is not needed.

**Verify.** `/Users/johnnysheng/code/origin-build/.venv/bin/python -m unittest wtdd.dog.test_audio.Driver.test_never_imports_the_drivers_audiohub -v` passes. It checks that no import line in audio.py names webrtc_audiohub or pydub, and that the module is absent from `sys.modules`.
