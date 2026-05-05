"""
AXIOM Voice Assistant — Core Engine
====================================
Do not run this file directly. Run server.py instead.

Pipeline:
  hotkey/wake-word → VAD recording → Whisper STT → Gemini (tool use) → TTS
"""

import asyncio
import json
import os
import random
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import google.generativeai as genai
import numpy as np
import sounddevice as sd
import whisper
import yaml
from dotenv import load_dotenv
from scipy.io.wavfile import write as wav_write

load_dotenv()

# ─── Load config ───────────────────────────────────────────────────────────────
with open("config.yaml") as _f:
    CFG = yaml.safe_load(_f)

ASSISTANT_NAME     = CFG["assistant"]["name"]
SAMPLE_RATE        = CFG["audio"]["sample_rate"]
MAX_RECORD_SECS    = CFG["audio"]["max_record_seconds"]
VAD_THRESHOLD      = CFG["audio"]["vad_energy_threshold"]
VAD_SILENCE_SECS   = CFG["audio"]["vad_silence_duration"]
MEMORY_FILE        = Path(CFG["memory"]["file"])
MAX_HISTORY        = CFG["memory"]["max_history"]
AUTO_SUMMARIZE_AFTER = CFG.get("memory", {}).get("auto_summarize_after", 20)
TTS_ENGINE         = CFG["tts"]["engine"]

# ─── Startup: load Whisper once ────────────────────────────────────────────────
print(f"[AXIOM] Loading Whisper ({CFG['whisper']['model']})…")
_whisper = whisper.load_model(CFG["whisper"]["model"])
print("[AXIOM] Whisper ready.")

# ─── Startup: init pygame mixer if using edge TTS ─────────────────────────────
if TTS_ENGINE == "edge":
    try:
        import pygame
        pygame.mixer.init()
        print("[AXIOM] pygame mixer ready.")
    except Exception as e:
        print(f"[AXIOM] pygame init failed ({e}), falling back to pyttsx3.")
        CFG["tts"]["engine"] = "pyttsx3"
        TTS_ENGINE = "pyttsx3"

# ─── Gemini client ────────────────────────────────────────────────────────────
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ─── State callback (wired up by server.py) ───────────────────────────────────
_emit: Optional[Callable] = None

def set_emit(fn: Callable):
    global _emit
    _emit = fn

def _send(event: str, data: dict = None):
    if _emit:
        _emit(event, data or {})

# ─── Persistent memory ────────────────────────────────────────────────────────

def load_history() -> list:
    if MEMORY_FILE.exists():
        with open(MEMORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data[-MAX_HISTORY:]
    return []


def save_history(history: list):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-MAX_HISTORY:], f, indent=2, ensure_ascii=False)


def _history_turn_count(history: list) -> int:
    return len([h for h in history if h.get("role") == "user"])


def _format_history_for_summary(history: list) -> str:
    lines = []
    for item in history:
        role = "User" if item.get("role") == "user" else ASSISTANT_NAME
        lines.append(f"{role}: {item.get('text', '')}")
    return "\n".join(lines)


def _maybe_summarize_history(history: list) -> list:
    """
    Keep recent exchanges verbatim and compress older context once the
    conversation crosses memory.auto_summarize_after user turns.
    """
    if not AUTO_SUMMARIZE_AFTER or _history_turn_count(history) <= AUTO_SUMMARIZE_AFTER:
        return history[-MAX_HISTORY:]

    recent = history[-8:]
    older = history[:-8]
    if not older:
        return history[-MAX_HISTORY:]

    try:
        model = genai.GenerativeModel(model_name=CFG["gemini"]["model"])
        prompt = (
            "Summarize this AXIOM voice-assistant conversation for future context. "
            "Keep stable preferences, project facts, decisions, and open tasks. "
            "Use plain text under 140 words.\n\n"
            f"{_format_history_for_summary(older)}"
        )
        response = model.generate_content(prompt)
        summary = response.text.strip()
        return [
            {
                "role": "user",
                "text": "Use this brief summary as context for the earlier conversation.",
            },
            {"role": "model", "text": summary},
        ] + recent
    except Exception as e:
        print(f"[AXIOM] Conversation summary failed ({e}); keeping recent history only.")
        return history[-MAX_HISTORY:]

# ─── VAD Recording ────────────────────────────────────────────────────────────

def record_audio() -> Optional[str]:
    """
    Record from microphone using energy-based VAD.
    Starts capturing on first loud chunk, stops after VAD_SILENCE_SECS of quiet.
    Returns path to a temp WAV file, or None if nothing was captured.
    """
    chunk_secs   = 0.08
    chunk_size   = int(SAMPLE_RATE * chunk_secs)
    max_chunks   = int(MAX_RECORD_SECS / chunk_secs)
    silence_need = int(VAD_SILENCE_SECS / chunk_secs)

    _send("state", {"state": "listening"})
    print(f"[AXIOM] Listening (threshold={VAD_THRESHOLD})…")

    chunks: list       = []
    silence_count: int = 0
    started: bool      = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        for _ in range(max_chunks):
            chunk, _ = stream.read(chunk_size)
            energy   = int(np.abs(chunk).mean())

            if energy > VAD_THRESHOLD:
                started       = True
                silence_count = 0
                chunks.append(chunk)
            elif started:
                chunks.append(chunk)
                silence_count += 1
                if silence_count >= silence_need:
                    break

    if not chunks:
        print("[AXIOM] No speech detected.")
        return None

    audio = np.concatenate(chunks, axis=0)
    tmp   = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_write(tmp.name, SAMPLE_RATE, audio)
    return tmp.name

# ─── Transcription ────────────────────────────────────────────────────────────

def transcribe(audio_path: str) -> str:
    _send("state", {"state": "transcribing"})
    result = _whisper.transcribe(audio_path, fp16=False)
    os.unlink(audio_path)
    text = result["text"].strip()
    print(f"[AXIOM] You said: {text}")
    return text

# ─── Gemini with tool use ─────────────────────────────────────────────────────

def _system_prompt() -> str:
    personality = CFG.get("assistant", {}).get("personality", {}) or {}
    tone = personality.get("tone", "casual")
    verbosity = personality.get("verbosity", "concise")
    return (
        f"You are {ASSISTANT_NAME}, a helpful personal voice assistant running on the user's PC. "
        f"Tone: {tone}. Verbosity: {verbosity}. "
        "Responses are spoken aloud, so keep them conversational and easy to hear. "
        "Avoid markdown, bullet points, and long lists unless the user specifically asks. "
        "Use your tools when needed for real-time information."
    )


def _slow_tool_acknowledgement(tool_name: str) -> None:
    slow_tools = {
        "run_scenario",
        "run_terminal",
        "run_git",
        "describe_screen",
        "search_web",
        "get_weather",
        "project_status",
    }
    if not CFG.get("assistant", {}).get("acknowledgements", True):
        return
    if tool_name not in slow_tools:
        return
    speak(random.choice(["Got it.", "On it.", "One moment."]))


def ask_ai(user_text: str, history: list) -> tuple[str, list]:
    """
    Send a message to Gemini, handle tool use, return (reply_text, updated_history).
    History is a simple list of {"role": "user"|"model", "text": "..."} dicts.
    Tool call turns are handled in-session and not persisted — only the final
    text exchange is saved, keeping memory.json clean and portable.
    """
    from tools import GEMINI_TOOLS, execute_tool

    # Convert stored text history to Gemini's content format
    gemini_history = [
        {"role": h["role"], "parts": [{"text": h["text"]}]}
        for h in history
    ]

    model = genai.GenerativeModel(
        model_name=CFG["gemini"]["model"],
        system_instruction=_system_prompt(),
        tools=GEMINI_TOOLS,
    )
    chat = model.start_chat(history=gemini_history)

    _send("state", {"state": "thinking"})
    response = chat.send_message(user_text)

    # Tool use loop
    while True:
        fn_calls = [p for p in response.parts if p.function_call.name] if response.parts else []
        if not fn_calls:
            break

        fn_responses = []
        for part in fn_calls:
            fn   = part.function_call
            args = dict(fn.args)
            print(f"[AXIOM] Tool: {fn.name}({args})")
            _send("tool",  {"name": fn.name, "input": args})
            _send("state", {"state": "tool"})
            _slow_tool_acknowledgement(fn.name)
            result = execute_tool(fn.name, args)
            fn_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fn.name, response={"result": result}
                    )
                )
            )

        _send("state", {"state": "thinking"})
        response = chat.send_message(fn_responses)

    reply = response.text.strip()
    print(f"[AXIOM] {ASSISTANT_NAME}: {reply}")

    updated_history = history + [
        {"role": "user",  "text": user_text},
        {"role": "model", "text": reply},
    ]
    return reply, _maybe_summarize_history(updated_history)

# ─── TTS ──────────────────────────────────────────────────────────────────────

_speech_interrupt = threading.Event()
_speaking = False


def _tts_config() -> dict:
    return CFG.get("tts", {}) or {}


def _split_for_tts(text: str) -> list[str]:
    """
    Split long responses into sentence-ish chunks so Edge TTS can start sooner.
    """
    if not _tts_config().get("sentence_streaming", True):
        return [text]
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts or [text]:
        candidate = f"{current} {part}".strip()
        if len(candidate) <= 220:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks or [text]


def request_activation(source: str = "manual") -> None:
    """
    Shared activation path for hotkey and wake word. If AXIOM is speaking,
    the same event also interrupts playback before the next listen cycle.
    """
    if _speaking and _tts_config().get("interruptible", True):
        _speech_interrupt.set()
        _send("log", {"level": "system", "text": f"Speech interrupted by {source}."})
    _wake_event.set()


def speak(text: str) -> bool:
    """
    Speak text. Returns True when playback was interrupted by a new activation.
    """
    global _speaking
    _speech_interrupt.clear()
    _speaking = True
    interrupted = False
    _send("state", {"state": "speaking"})
    try:
        for chunk in _split_for_tts(text):
            if _speech_interrupt.is_set():
                interrupted = True
                break
            if CFG["tts"]["engine"] == "edge":
                interrupted = _speak_edge(chunk)
            else:
                interrupted = _speak_pyttsx3(chunk)
            if interrupted:
                break
    finally:
        _speaking = False
        _send("state", {"state": "idle"})
    return interrupted


def _speak_edge(text: str) -> bool:
    async def _run():
        import edge_tts
        import pygame
        voice       = CFG["tts"]["edge_voice"]
        communicate = edge_tts.Communicate(text, voice)
        tmp         = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        await communicate.save(tmp.name)
        return tmp.name

    try:
        mp3_path = asyncio.run(_run())
        import pygame
        pygame.mixer.music.load(mp3_path)
        pygame.mixer.music.play()
        interrupted = False
        while pygame.mixer.music.get_busy():
            if _speech_interrupt.is_set():
                pygame.mixer.music.stop()
                interrupted = True
                break
            time.sleep(0.05)
        pygame.mixer.music.unload()
        os.unlink(mp3_path)
        return interrupted
    except Exception as e:
        print(f"[AXIOM] edge-tts error ({e}), falling back to pyttsx3.")
        return _speak_pyttsx3(text)


def _speak_pyttsx3(text: str) -> bool:
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate",   CFG["tts"]["pyttsx3_rate"])
    engine.setProperty("volume", CFG["tts"]["pyttsx3_volume"])
    engine.say(text)
    engine.runAndWait()
    return _speech_interrupt.is_set()

# ─── Project Registry & Scenario Engine ───────────────────────────────────────

_project_registry = None
_scenario_engine  = None


def init_project_registry():
    """
    Construct the ProjectRegistry and register it with tools.py.
    Called by init_scenario_engine() so the engine can use it for resolution.
    """
    global _project_registry
    from projects import ProjectRegistry
    from tools    import set_project_registry

    _project_registry = ProjectRegistry(CFG)
    set_project_registry(_project_registry)
    print(f"[AXIOM] Project registry ready ({len(_project_registry.list_projects())} projects).")
    return _project_registry


def init_scenario_engine():
    """
    Construct the ProjectRegistry first, then the ScenarioEngine that uses it.
    Both are registered with tools.py so the `run_scenario`, `list_projects`,
    `project_status`, `switch_project` tools can dispatch to them.

    Must be called AFTER set_emit() so that emit_fn is wired correctly.
    """
    global _scenario_engine

    registry = init_project_registry()

    from scenarios import ScenarioEngine
    from tools     import execute_tool, set_scenario_engine

    _scenario_engine = ScenarioEngine(
        config           = CFG,
        speak_fn         = speak,
        emit_fn          = lambda event, data=None: _send(event, data or {}),
        tool_executor    = execute_tool,
        record_fn        = record_audio,
        transcribe_fn    = transcribe,
        project_registry = registry,
    )
    set_scenario_engine(_scenario_engine)
    print(f"[AXIOM] Scenario engine ready ({len(_scenario_engine.list_scenarios())} scenarios).")
    return _scenario_engine


# ─── Optional: openwakeword background listener ───────────────────────────────
# (Only activated when wake_word.enabled = true in config.yaml)

_wake_event = threading.Event()


def _wake_config() -> dict:
    return CFG.get("wake_word", {}) or {}


def _download_wake_models(openwakeword_module, retries: int) -> bool:
    for attempt in range(1, retries + 1):
        try:
            openwakeword_module.utils.download_models()
            return True
        except Exception as e:
            msg = f"Wake model download failed ({attempt}/{retries}): {e}"
            print(f"[AXIOM] {msg}")
            _send("log", {"level": "warn", "text": msg})
            time.sleep(min(2 * attempt, 8))
    return False


def _build_wake_model_args(wake_cfg: dict) -> list[str]:
    model_path = str(wake_cfg.get("model_path", "") or "").strip()
    if model_path:
        return [model_path]
    return [wake_cfg.get("model", "hey_jarvis")]


def _oww_listener():
    """
    Runs in a daemon thread when wake_word.enabled = true.
    Sets _wake_event when the wake word is detected.
    """
    try:
        import openwakeword
        from openwakeword.model import Model as OWWModel

        wake_cfg = _wake_config()
        retries = int(wake_cfg.get("download_retries", 3))
        if not _download_wake_models(openwakeword, retries):
            msg = "Wake word disabled after model download retries. Hotkey remains active."
            print(f"[AXIOM] {msg}")
            _send("log", {"level": "warn", "text": msg})
            return

        threshold = float(wake_cfg.get("threshold", 0.5))
        cooldown = float(wake_cfg.get("cooldown_seconds", 3))
        model_args = _build_wake_model_args(wake_cfg)
        oww = OWWModel(wakeword_models=model_args, inference_framework="onnx")
        chunk = int(SAMPLE_RATE * 0.08)
        last_detection = 0.0
        msg = f"Wake word active ({model_args[0]}, threshold={threshold}, cooldown={cooldown}s)."
        print(f"[AXIOM] {msg}")
        _send("log", {"level": "system", "text": msg})
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            while True:
                data, _ = stream.read(chunk)
                scores  = oww.predict(data.flatten())
                now = time.monotonic()
                if any(v >= threshold for v in scores.values()) and now - last_detection >= cooldown:
                    last_detection = now
                    print("[AXIOM] Wake word detected!")
                    _send("log", {"level": "system", "text": "Wake word detected."})
                    request_activation("wake word")
    except Exception as e:
        msg = f"Wake word failed ({e}). Hotkey remains active."
        print(f"[AXIOM] {msg}")
        _send("log", {"level": "warn", "text": msg})


def start_wake_word_listener() -> bool:
    if not _wake_config().get("enabled", False):
        return False
    t = threading.Thread(target=_oww_listener, daemon=True)
    t.start()
    return True
