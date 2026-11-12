"""Optional engine: Azure Speech (REST). Reads AZURE_SPEECH_KEY and AZURE_SPEECH_REGION from the environment."""
from __future__ import annotations

import io
import os
import urllib.request
from xml.sax.saxutils import escape

import numpy as np


class AzureEngine:
    name = "azure"

    def __init__(self, voice: str = "en-US-AvaMultilingualNeural", speed: float = 1.0, **_):
        self.key = os.environ.get("AZURE_SPEECH_KEY")
        self.region = os.environ.get("AZURE_SPEECH_REGION")
        if not self.key or not self.region:
            raise RuntimeError("Azure engine needs AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in the environment")
        self.voice = voice
        self.speed = float(speed)
        self.rate = f"{round((self.speed - 1) * 100):+d}%"

    def synthesize(self, text: str, speed: float | None = None) -> tuple[np.ndarray, int]:
        import soundfile as sf

        rate = self.rate if speed is None else f"{round((float(speed) - 1) * 100):+d}%"

        ssml = (
            "<speak version='1.0' xml:lang='en-US'>"
            f"<voice name='{self.voice}'><prosody rate='{rate}'>{escape(text)}</prosody></voice></speak>"
        )
        req = urllib.request.Request(
            f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1",
            data=ssml.encode("utf-8"),
            headers={
                "Ocp-Apim-Subscription-Key": self.key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
                "User-Agent": "script-to-explainer",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data, sr = sf.read(io.BytesIO(r.read()), dtype="float32")
        return np.asarray(data, dtype=np.float32), int(sr)
