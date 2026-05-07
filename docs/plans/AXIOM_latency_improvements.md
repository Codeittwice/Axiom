# AXIOM — Latency Improvement Plan

> Goal: Reduce response time and make interactions feel near-instant
> Current stack: Electron + JavaScript | Gemini API | Whisper STT | edge-tts

---

## Current Bottlenecks

| Step | Issue | Estimated Delay |
|---|---|---|
| Recording | Fixed-length recording window | +2–4s wasted silence |
| STT | Whisper Python (if still used) | 1–3s transcription |
| LLM | Waiting for full Gemini response | 0.5–1s perceived lag |
| TTS | edge-tts waits for full text before speaking | 0.3–0.8s delay |

---

## Improvement 1 — Voice Activity Detection (VAD) ⭐ Highest Impact

**What it does:** Automatically stops recording the moment you finish speaking, instead of waiting a fixed number of seconds.

**Recommended tool:** [Silero VAD](https://github.com/snakers4/silero-vad) via ONNX Runtime

**How to integrate in Electron:**

```bash
npm install onnxruntime-node
```

```javascript
const ort = require('onnxruntime-node');

// Load the Silero VAD model (download silero_vad.onnx once)
const session = await ort.InferenceSession.create('./models/silero_vad.onnx');

// In your audio capture loop:
function isSpeech(audioChunk) {
  const input = new ort.Tensor('float32', audioChunk, [1, audioChunk.length]);
  const output = await session.run({ input });
  return output.output.data[0] > 0.5; // confidence threshold
}

// Stop recording when speech ends
let silenceFrames = 0;
const SILENCE_LIMIT = 15; // ~0.5s of silence at 30ms chunks

audioStream.on('data', async (chunk) => {
  const speaking = await isSpeech(chunk);
  if (!speaking) {
    silenceFrames++;
    if (silenceFrames >= SILENCE_LIMIT) stopRecording(); // cut off immediately
  } else {
    silenceFrames = 0; // reset on speech
  }
});
```

**Expected saving:** 2–4 seconds per interaction

---

## Improvement 2 — Gemini Streaming + TTS Pipeline ⭐ High Impact

**What it does:** Instead of waiting for Gemini's full response, stream tokens as they arrive and feed them to edge-tts sentence by sentence. Axiom starts speaking before it has finished "thinking."

**How it works:**

```javascript
const { GoogleGenerativeAI } = require('@google/generative-ai');
const edgeTTS = require('edge-tts'); // or your current edge-tts wrapper

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({ model: 'gemini-1.5-flash' });

async function streamResponse(userText) {
  const result = await model.generateContentStream(userText);

  let buffer = '';

  for await (const chunk of result.stream) {
    const text = chunk.text();
    buffer += text;

    // Speak each complete sentence as it arrives
    const sentences = buffer.match(/[^.!?]+[.!?]+/g);
    if (sentences) {
      for (const sentence of sentences) {
        await speakWithEdgeTTS(sentence.trim());
      }
      // Keep remainder (incomplete sentence) in buffer
      buffer = buffer.replace(/[^.!?]+[.!?]+/g, '');
    }
  }

  // Speak any remaining text
  if (buffer.trim()) await speakWithEdgeTTS(buffer.trim());
}

async function speakWithEdgeTTS(text) {
  // Call your existing edge-tts integration here
  // e.g. edge_tts.communicate(text, voice="en-US-GuyNeural")
}
```

**Expected saving:** 0.5–1.5s perceived latency — Axiom starts speaking almost immediately

---

## Improvement 3 — Switch to faster-whisper (If Using Python Whisper)

**What it does:** Drop-in replacement for OpenAI Whisper using CTranslate2 backend — ~4x faster with the same accuracy.

```bash
pip install faster-whisper
```

```python
from faster_whisper import WhisperModel

# Use "base" or "small" for best speed/accuracy balance
model = WhisperModel("base", device="cpu", compute_type="int8")

segments, info = model.transcribe("audio.wav", beam_size=1)
transcription = " ".join([s.text for s in segments])
```

> If you've already moved STT fully into the browser (Web Speech API), skip this — you're already faster.

**Expected saving:** 1–2s per transcription

---

## Recommended Implementation Order

1. **VAD first** — biggest real-world impact, no changes to Gemini or TTS needed
2. **Gemini streaming + TTS pipeline** — makes Axiom feel alive and responsive
3. **faster-whisper** — only if STT is still a bottleneck after steps 1 & 2

---

## Quick Reference: Full Optimised Flow

```
[User speaks]
     ↓
[VAD detects speech start → records]
     ↓
[VAD detects silence → stops immediately]
     ↓
[Whisper / Web Speech API transcribes]
     ↓
[Gemini stream starts]
     ↓
[First sentence ready → edge-tts speaks it]  ← happens in parallel
[Second sentence ready → edge-tts queues it]
[...continues until response complete]
```

---

*Generated: May 2026 | Part of the AXIOM development plan*
