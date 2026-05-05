"""
AXIOM wake-word sample collector.

This prepares local audio samples for a future custom "Hey Axiom" openWakeWord
model. It records positive and negative examples into custom_models/wake_word/.
The actual model training step still belongs to the openWakeWord training
pipeline, because that pipeline has separate dataset and accelerator needs.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write


SAMPLE_RATE = 16000


def record_clip(seconds: float) -> np.ndarray:
    audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    return audio


def collect_samples(label: str, count: int, seconds: float, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        print(f"{label} sample {i}/{count}: recording starts in 1 second...")
        time.sleep(1)
        audio = record_clip(seconds)
        path = out_dir / f"{label}_{i:03d}.wav"
        wav_write(path, SAMPLE_RATE, audio)
        print(f"saved {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Hey Axiom wake-word samples.")
    parser.add_argument("--positive", type=int, default=30, help="Number of Hey Axiom samples.")
    parser.add_argument("--negative", type=int, default=10, help="Number of background/silence samples.")
    parser.add_argument("--seconds", type=float, default=1.5, help="Seconds per clip.")
    parser.add_argument("--out", default="custom_models/wake_word", help="Output directory.")
    args = parser.parse_args()

    root = Path(args.out)
    print("Say 'Hey Axiom' naturally for positive samples.")
    collect_samples("positive", args.positive, args.seconds, root / "positive")
    print("Stay silent or make normal background noise for negative samples.")
    collect_samples("negative", args.negative, args.seconds, root / "negative")
    print("Samples collected. Use the openWakeWord training pipeline to export hey_axiom.onnx.")


if __name__ == "__main__":
    main()
