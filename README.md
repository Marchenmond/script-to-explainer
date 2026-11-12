# script-to-explainer

Turn a JSON script into a narrated 1080p explainer video, rendered locally with one command.
Bit, a small pixel-art robot, presents your slides, reacts with simple emotions, and moves its mouth with the voice. Captions are timed to the narration.

No cloud, no account: the default voice (Kokoro) runs on your machine.

## Requirements

- Python 3.10 or newer
- [ffmpeg](https://ffmpeg.org/download.html) on your PATH
- About 350 MB of disk for the voice model (downloaded once, on the first render)

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e .            # Windows: .venv\Scripts\pip install -e .
.venv/bin/python -m explainer render examples/demo.json -o out/demo.mp4
```

You get `out/demo.mp4` (1920x1080, 30 fps, about 48 s) and `out/demo.srt` (the captions as a separate file).
Check a script without rendering: `python -m explainer validate examples/demo.json`.
Quick look at the layout only: add `--preview` (writes one PNG per scene).

## The script format

```json
{
  "title": "My video",
  "voice": { "engine": "kokoro", "voice": "af_heart", "speed": 1.0 },
  "scenes": [
    {
      "say": "Hi, I'm Bit. Welcome!",
      "emotion": "happy",
      "pause_after": 0.5,
      "slide": { "type": "title", "kicker": "Intro", "title": "Hello", "subtitle": "Nice to meet you" }
    }
  ]
}
```

| Field | Values |
| --- | --- |
| `emotion` | `neutral`, `happy`, `thinking`, `pointing` |
| `slide.type` | `title` (kicker, title, subtitle), `bullets` (title, items: shown one by one while Bit speaks), `highlight` (title, highlight, subtitle) |
| `pause_after` | seconds of silence after the scene, 0 to 10 (default 0.5) |
| `voice` | engine name plus engine options (voice, speed) |

Narration is English. Each sentence is spoken and captioned separately, so captions line up with the audio.

## Voices (swappable engine)

| Engine | Notes |
| --- | --- |
| `kokoro` (default) | Local and free. Voices such as `af_heart`, `af_bella`, `am_adam`, `bf_emma`, `bm_george`. |
| `azure` | Optional. Set `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`, then use `--engine azure` or `"engine": "azure"` in the script, e.g. `"voice": "en-US-AvaMultilingualNeural"`. |

Choose at render time: `python -m explainer render demo.json --engine azure`.
To add another engine, implement `synthesize(text) -> (samples, sample_rate)` in `src/explainer/tts/` and register it in `tts/__init__.py`.
Set `EXPLAINER_MODELS` to keep the Kokoro model files somewhere else (default: `./models`).

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

## Credits and licenses

- Code: MIT, see `LICENSE`.
- Font: JetBrains Mono, SIL Open Font License 1.1 (`src/explainer/assets/fonts/OFL.txt`).
- Voice: [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) through [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), both Apache 2.0. Model files are downloaded, not stored in this repository.
- Bit (pixel art): original artwork for this project, MIT like the code.
- Slide colors follow the Catppuccin Mocha palette (MIT).

Phase 2 (planned): polished README with a GIF preview.
