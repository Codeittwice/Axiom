"""
AXIOM Voice Assistant — Core Engine
====================================
Do not run this file directly. Run server.py instead.

Pipeline:
  hotkey/wake-word → VAD recording → Whisper STT → Gemini (tool use) → TTS
"""

import asyncio
from collections import deque
from dataclasses import dataclass
import json
import os
import queue
import random
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import google.generativeai as genai
import numpy as np
import sounddevice as sd
try:
    from faster_whisper import WhisperModel as _FasterWhisperModel
    _FASTER_WHISPER = True
except ImportError:
    _FasterWhisperModel = None
    _FASTER_WHISPER = False
try:
    import whisper as _openai_whisper
    _OPENAI_WHISPER = True
except ImportError:
    _openai_whisper = None
    _OPENAI_WHISPER = False
import yaml
from dotenv import load_dotenv
from scipy.io.wavfile import write as wav_write

from text_safety import clean_text, console_text

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
_whisper_model_name = CFG["whisper"]["model"]
_requested_whisper_engine = str(CFG.get("whisper", {}).get("engine", "faster") or "faster").lower()
if _requested_whisper_engine == "openai" and _OPENAI_WHISPER:
    print(f"[AXIOM] Loading Whisper ({_whisper_model_name})...")
    _whisper = _openai_whisper.load_model(_whisper_model_name)
    _WHISPER_ENGINE = "openai"
elif _FASTER_WHISPER:
    print(f"[AXIOM] Loading faster-whisper ({_whisper_model_name})…")
    _whisper = _FasterWhisperModel(
        _whisper_model_name,
        device="cpu",
        compute_type="int8",
    )
    _WHISPER_ENGINE = "faster"
elif _OPENAI_WHISPER:
    print(f"[AXIOM] Loading Whisper ({_whisper_model_name})...")
    _whisper = _openai_whisper.load_model(_whisper_model_name)
    _WHISPER_ENGINE = "openai"
else:
    raise RuntimeError("No Whisper backend is installed. Install faster-whisper or openai-whisper.")
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


@dataclass
class AIResult:
    reply: str
    history: list
    spoke: bool = False
    interrupted: bool = False
    tools_called: list = None

    def __post_init__(self):
        if self.tools_called is None:
            self.tools_called = []

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
        lines.append(f"{role}: {clean_text(item.get('text', ''))}")
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
        model = genai.GenerativeModel(
            model_name=CFG["gemini"]["model"],
            generation_config=_gemini_generation_config(),
        )
        prompt = (
            "Summarize this AXIOM voice-assistant conversation for future context. "
            "Keep stable preferences, project facts, decisions, and open tasks. "
            "Use plain text under 140 words.\n\n"
            f"{_format_history_for_summary(older)}"
        )
        response = model.generate_content(prompt)
        summary = clean_text(response.text.strip())
        return [
            {
                "role": "user",
                "text": "Use this brief summary as context for the earlier conversation.",
            },
            {"role": "model", "text": summary},
        ] + recent
    except Exception as e:
        print(console_text(f"[AXIOM] Conversation summary failed ({e}); keeping recent history only."))
        return history[-MAX_HISTORY:]

# ─── VAD Recording ────────────────────────────────────────────────────────────

def record_audio(wait_for_speech_seconds: Optional[float] = None) -> Optional[str]:
    """
    Record from microphone using energy-based VAD.
    Starts capturing on first loud chunk, stops after VAD_SILENCE_SECS of quiet.
    wait_for_speech_seconds controls how long to wait for speech to begin.
    Returns path to a temp WAV file, or None if nothing was captured.
    """
    chunk_secs   = 0.08
    chunk_size   = int(SAMPLE_RATE * chunk_secs)
    max_speech_chunks = int(MAX_RECORD_SECS / chunk_secs)
    wait_secs = wait_for_speech_seconds if wait_for_speech_seconds is not None else MAX_RECORD_SECS
    max_idle_chunks = max(1, int(float(wait_secs) / chunk_secs))
    silence_need = int(VAD_SILENCE_SECS / chunk_secs)
    pre_roll_secs = float(CFG.get("audio", {}).get("pre_roll_seconds", 0.35) or 0)
    pre_roll = deque(maxlen=max(1, int(pre_roll_secs / chunk_secs)))

    _send("state", {"state": "listening"})
    print(f"[AXIOM] Listening (threshold={VAD_THRESHOLD}, wait={wait_secs:.0f}s)...")

    chunks: list       = []
    silence_count: int = 0
    speech_chunks: int = 0
    idle_chunks: int   = 0
    started: bool      = False

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
        while True:
            chunk, _ = stream.read(chunk_size)
            energy   = int(np.abs(chunk).mean())

            if energy > VAD_THRESHOLD:
                if not started:
                    chunks.extend(pre_roll)
                started       = True
                silence_count = 0
                speech_chunks += 1
                chunks.append(chunk)
            elif started:
                chunks.append(chunk)
                speech_chunks += 1
                silence_count += 1
                if silence_count >= silence_need:
                    break
            else:
                pre_roll.append(chunk)
                idle_chunks += 1
                if idle_chunks >= max_idle_chunks:
                    break

            if started and speech_chunks >= max_speech_chunks:
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
    whisper_cfg = CFG.get("whisper", {}) or {}

    if _WHISPER_ENGINE == "faster":
        options = {
            "beam_size": int(whisper_cfg.get("beam_size", 5) or 5),
            "temperature": float(whisper_cfg.get("temperature", 0) or 0),
            "condition_on_previous_text": bool(whisper_cfg.get("condition_on_previous_text", False)),
        }
        if whisper_cfg.get("language"):
            options["language"] = whisper_cfg["language"]
        if whisper_cfg.get("initial_prompt"):
            options["initial_prompt"] = whisper_cfg["initial_prompt"]
        if whisper_cfg.get("no_speech_threshold") is not None:
            options["no_speech_threshold"] = float(whisper_cfg["no_speech_threshold"])
        if whisper_cfg.get("logprob_threshold") is not None:
            options["log_prob_threshold"] = float(whisper_cfg["logprob_threshold"])
        segments, _ = _whisper.transcribe(audio_path, **options)
        raw = " ".join(s.text for s in segments)
    else:
        options = {
            "fp16": False,
            "temperature": float(whisper_cfg.get("temperature", 0) or 0),
            "condition_on_previous_text": bool(whisper_cfg.get("condition_on_previous_text", False)),
        }
        if whisper_cfg.get("language"):
            options["language"] = whisper_cfg["language"]
        if whisper_cfg.get("initial_prompt"):
            options["initial_prompt"] = whisper_cfg["initial_prompt"]
        if whisper_cfg.get("no_speech_threshold") is not None:
            options["no_speech_threshold"] = float(whisper_cfg["no_speech_threshold"])
        if whisper_cfg.get("logprob_threshold") is not None:
            options["logprob_threshold"] = float(whisper_cfg["logprob_threshold"])
        result = _whisper.transcribe(audio_path, **options)
        raw = result.get("text", "")

    os.unlink(audio_path)
    text = clean_text(raw, collapse_whitespace=True)
    print(console_text(f"[AXIOM] You said: {text}"))
    return text

# ─── Gemini with tool use ─────────────────────────────────────────────────────

def _system_prompt() -> str:
    personality = CFG.get("assistant", {}).get("personality", {}) or {}
    tone = personality.get("tone", "casual")
    verbosity = personality.get("verbosity", "concise")

    profile_section = ""
    try:
        from user_profile import read_profile
        profile_text = read_profile(CFG)
        if profile_text:
            profile_section = (
                f"\n\nHere is what you know about the user:\n{profile_text}\n"
                "Use this to personalise your responses naturally. "
                "Don't mention the profile unless directly relevant."
            )
    except Exception:
        pass

    return (
        f"You are {ASSISTANT_NAME}, a helpful personal voice assistant running on the user's PC. "
        f"Tone: {tone}. Verbosity: {verbosity}. "
        "Responses are spoken aloud, so keep them conversational and easy to hear. "
        "Avoid markdown, bullet points, and long lists unless the user specifically asks. "
        "Tool use rules: "
        "ALWAYS call search_web for any question about prices, travel costs, current events, news, "
        "real-time facts, live availability, recent product details, or anything you cannot answer with certainty from training data — never guess. "
        "For broad factual questions such as 'what is', 'how much', 'tell me about', or 'how does this work', use search_web when freshness or accuracy could matter. "
        "Call get_weather for weather questions. "
        "Call today_schedule or next_event for calendar questions. "
        "Call edit_task or delete_task when the user asks to edit, change, reprioritize, remove, or delete an Obsidian task. "
        "Call check_axiom_status when the user asks about AXIOM's status, health, setup, integrations, or wake-word configuration. "
        "Call get_last_commit_message when asked about the latest commit or recent changes. "
        "Call remember_preference when the user says 'remember that', 'I prefer', 'I always', 'I never', 'I like', 'I hate', 'I want', or 'from now on' — save it to memory first, then acknowledge. "
        "Call recall_memory when the user says 'do you remember', 'what did I say about', 'have I told you', or asks about a past preference or conversation. "
        "When in doubt between answering from memory and calling a tool, call the tool."
        + profile_section
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


def _gemini_generation_config() -> dict:
    gemini_cfg = CFG.get("gemini", {}) or {}
    config: dict = {}
    max_tokens = int(gemini_cfg.get("max_tokens", 0) or 0)
    if max_tokens > 0:
        config["max_output_tokens"] = max_tokens
    return config


def _parse_spoken_due(text: str) -> str:
    lowered = text.lower()
    now = datetime.now().astimezone()
    if "tomorrow" in lowered:
        return (now + timedelta(days=1)).date().isoformat()
    if "today" in lowered:
        return now.date().isoformat()
    match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    return match.group(1) if match else ""


def _parse_spoken_priority(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b(high|height)\s+priority\b|\bpriority\s+(?:of\s+)?(?:high|height)\b", lowered):
        return "high"
    if re.search(r"\bmedium\s+priority\b|\bpriority\s+(?:of\s+)?medium\b", lowered):
        return "medium"
    if re.search(r"\blow\s+priority\b|\bpriority\s+(?:of\s+)?low\b", lowered):
        return "low"
    return ""


def _task_text_from_request(user_text: str) -> str:
    text = clean_text(user_text, collapse_whitespace=True)
    text = re.sub(
        r"^(?:please\s+)?(?:add|create|make|capture)\s+(?:a\s+)?(?:new\s+)?(?:task|todo|to do)\s*(?:to|for)?\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"^(?:please\s+)?remind me to\s+", "", text, flags=re.I)
    text = re.sub(r"\b(?:it'?s\s+)?(?:a\s+)?(?:high|height|medium|low)\s+priority\b\.?", "", text, flags=re.I)
    text = re.sub(r"\bpriority\s+(?:of\s+)?(?:high|height|medium|low)\b\.?", "", text, flags=re.I)
    return clean_text(text.strip(" .,-"), collapse_whitespace=True)


def _search_query_from_request(user_text: str) -> str:
    text = clean_text(user_text, collapse_whitespace=True)
    if re.search(r"\bthis error\b", text, re.I):
        return "Gemini did not return a spoken response Finish reason 1 Streaming response was empty"
    query = re.sub(
        r"^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|google)\s+",
        "",
        text,
        flags=re.I,
    )
    return clean_text(query.strip(" .,-"), collapse_whitespace=True) or text


def _direct_tool_for_text(user_text: str) -> Optional[tuple[str, dict]]:
    """
    Deterministic routing for high-friction local-control requests.
    This keeps Gemini from guessing about local config when the repo has tools.
    """
    text = user_text.lower()

    # Profile voice commands
    if any(phrase in text for phrase in ("let's do onboarding", "lets do onboarding", "set up my profile", "setup my profile", "start onboarding")):
        return "start_onboarding", {}
    if any(phrase in text for phrase in ("update my profile", "ask me something", "ask me a question")):
        return "ask_profile_question", {}
    if (("what do you know" in text or "tell me" in text or "read" in text) and "about me" in text) or "know about me" in text:
        return "read_profile_aloud", {}
    if any(phrase in text for phrase in ("forget that", "that's wrong", "that was wrong", "ignore that")):
        return "flag_last_fact", {}

    has_calendar = "calendar" in text or "schedule" in text or "meeting" in text or "event" in text
    has_email = "email" in text or "mail" in text or "gmail" in text or "inbox" in text
    has_obsidian = "obsidian" in text or "vault" in text
    has_spotify = "spotify" in text or "music" in text or "song" in text or "track" in text
    has_task = "task" in text or "todo" in text or "to do" in text or "remind me" in text
    has_axiom = "axiom" in text or "assistant" in text or "voice assistant" in text
    config_words = ("config", "setting", "enabled", "disabled", "true", "false", "check")
    email_status_words = ("config", "setting", "enabled", "disabled", "true", "false", "status")
    search_starters = ("what is", "what are", "who is", "how much", "how many", "tell me about", "look up", "search for")

    if has_axiom and any(word in text for word in ("status", "state", "health", "setup", "configured", "configuration", "wake word", "integrations")):
        return "check_axiom_status", {}
    if re.match(r"^(?:please\s+)?(?:search(?:\s+the\s+web)?(?:\s+for)?|look\s+up|google)\b", text):
        return "search_web", {"query": _search_query_from_request(user_text)}
    if has_obsidian and (
        "workflow" in text
        or "plan" in text
        or "explain" in text
        or "implementation" in text
        or "how will" in text
    ):
        return "explain_obsidian_workflow", {}
    if (has_obsidian or has_task) and ("status" in text or "configured" in text):
        return "obsidian_status", {}
    if has_task and (
        "high priority" in text
        or "priority high" in text
        or "important" in text
        or "urgent" in text
        or "tackle first" in text
    ):
        return "list_tasks", {"priority": "high", "limit": 8}
    if has_task and ("today" in text or "due now" in text):
        return "today_tasks", {}
    if has_task and ("upcoming" in text or "this week" in text or "next week" in text):
        return "upcoming_tasks", {"days": 7}
    if has_task and any(word in text for word in ("list", "show", "read", "what are", "what's", "which")):
        return "list_tasks", {"limit": 8}
    if (
        re.search(r"\b(?:add|create|make|capture)\b.*\b(?:task|todo|to do)\b", text)
        or re.search(r"\bremind me to\b", text)
    ) and not any(word in text for word in ("delete", "remove", "edit", "change", "update", "complete", "done")):
        task_text = _task_text_from_request(user_text)
        if len(task_text.split()) >= 3:
            return "capture_task", {
                "text": task_text,
                "due": _parse_spoken_due(user_text),
                "priority": _parse_spoken_priority(user_text),
            }
    if has_task and (
        "delete" in text
        or "remove" in text
        or "edit" in text
        or "change" in text
        or "update" in text
        or "priority" in text
        or "weight" in text
    ):
        return None
    if has_calendar and any(word in text for word in config_words):
        return "calendar_status", {}
    if has_email and ("connect" in text or "authorize" in text or "authorise" in text or "consent" in text):
        return "connect_gmail", {}
    if has_email and any(word in text for word in email_status_words):
        return "gmail_status", {}
    if has_spotify and ("connect" in text or "authorize" in text or "authorise" in text or "configure" in text):
        return "connect_spotify", {}
    if has_spotify and ("status" in text or "configured" in text or "enabled" in text):
        return "spotify_status", {}
    if has_spotify and ("what" in text or "current" in text or "now playing" in text):
        return "spotify_now_playing", {}
    if has_spotify and ("pause" in text or "stop" in text):
        return "spotify_control", {"action": "pause"}
    if has_spotify and ("resume" in text or "play" in text) and not any(word in text for word in ("song", "track", "music")):
        return "spotify_control", {"action": "play"}
    if has_email and ("mark" in text or "reset" in text) and "check" in text:
        return "mark_email_check", {}
    if has_email and ("new" in text or "since" in text):
        return "new_emails", {}
    if has_email and "unread" in text:
        return "unread_count", {}
    if has_email and ("recent" in text or "latest" in text or "last" in text):
        return "last_emails", {"n": 5}
    if has_email and ("summary" in text or "summarize" in text or "summarise" in text):
        return "summarize_inbox", {}
    if has_email and ("check" in text or "what" in text or "any" in text):
        return "new_emails", {}
    if has_calendar and "this week" in text:
        now = datetime.now().astimezone()
        end = (now + timedelta(days=7 - now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return "list_events", {"start": now.isoformat(), "end": end.isoformat()}
    if has_calendar and "next week" in text:
        now = datetime.now().astimezone()
        start = (now + timedelta(days=7 - now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)
        return "list_events", {"start": start.isoformat(), "end": end.isoformat()}
    if has_calendar and "tomorrow" in text:
        start = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return "list_events", {"start": start.isoformat(), "end": end.isoformat()}
    if has_calendar and "this month" in text:
        now = datetime.now().astimezone()
        end = (now.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return "list_events", {"start": now.isoformat(), "end": end.isoformat()}
    if "schedule" in text and ("today" in text or "what" in text or "what's" in text):
        return "today_schedule", {}
    if "calendar" in text and "today" in text:
        return "today_schedule", {}
    if ("next" in text or "upcoming" in text) and ("meeting" in text or "event" in text or "calendar" in text):
        return "next_event", {}
    if any(text.startswith(prefix) for prefix in search_starters) and not any(
        marker in text
        for marker in (
            "weather",
            "calendar",
            "schedule",
            "email",
            "gmail",
            "spotify",
            "task",
            "todo",
            "repo",
            "project status",
            "remember",
        )
    ):
        return "search_web", {"query": user_text}
    return None


def _can_stream_text_reply(user_text: str) -> bool:
    """
    Stream normal conversational replies. Local-control/tool-ish requests stay
    on the non-streaming path so Gemini can still emit function calls reliably.
    """
    text = user_text.lower()
    tool_markers = (
        "open ",
        "launch ",
        "start ",
        "run ",
        "search",
        "look up",
        "google",
        "status",
        "state",
        "health",
        "axiom",
        "weather",
        "calendar",
        "schedule",
        "meeting",
        "event",
        "email",
        "mail",
        "gmail",
        "inbox",
        "spotify",
        "music",
        "timer",
        "task",
        "todo",
        "to do",
        "remind me",
        "volume",
        "note",
        "obsidian",
        "vault",
        "repo",
        "project",
        "codebase",
        "diff",
        "file",
        "screen",
        "screenshot",
        "website",
        "github",
        "scenario",
    )
    return not any(marker in text for marker in tool_markers)


def ask_ai(user_text: str, history: list, speak_response: bool = False) -> AIResult:
    """
    Send a message to Gemini, handle tool use, return (reply_text, updated_history, tools_called).
    History is a simple list of {"role": "user"|"model", "text": "..."} dicts.
    Tool call turns are handled in-session and not persisted — only the final
    text exchange is saved, keeping memory.json clean and portable.
    """
    from tools import GEMINI_TOOLS, execute_tool
    user_text = clean_text(user_text)
    _tools_called: list[str] = []

    direct_tool = _direct_tool_for_text(user_text)
    if direct_tool:
        name, args = direct_tool
        print(console_text(f"[AXIOM] Direct tool: {name}({args})"))
        _send("tool", {"name": name, "input": args})
        _send("state", {"state": "tool"})
        _tools_called.append(name)
        reply = clean_text(execute_tool(name, args))
        print(console_text(f"[AXIOM] {ASSISTANT_NAME}: {reply}"))
        updated_history = history + [
            {"role": "user", "text": user_text},
            {"role": "model", "text": reply},
        ]
        _send("state", {"state": "idle"})
        return AIResult(reply=reply, history=_maybe_summarize_history(updated_history), tools_called=_tools_called)

    # Convert stored text history to Gemini's content format
    gemini_history = [
        {"role": h["role"], "parts": [{"text": clean_text(h["text"])}]}
        for h in history
    ]

    # Brain recall — prepend relevant long-term context as a synthetic history turn
    try:
        from brain import recall
        _brain_ctx = recall(user_text, CFG, max_tokens=400)
        if _brain_ctx:
            gemini_history = [
                {"role": "user",  "parts": [{"text": f"[AXIOM memory context]\n{_brain_ctx}"}]},
                {"role": "model", "parts": [{"text": "Understood, I'll keep this context in mind."}]},
            ] + gemini_history
    except Exception:
        pass

    model = genai.GenerativeModel(
        model_name=CFG["gemini"]["model"],
        system_instruction=_system_prompt(),
        tools=GEMINI_TOOLS,
        generation_config=_gemini_generation_config(),
    )
    chat = model.start_chat(history=gemini_history)

    if speak_response and _tts_config().get("gemini_streaming", True) and _can_stream_text_reply(user_text):
        try:
            _send("state", {"state": "thinking"})
            response_stream = chat.send_message(user_text, stream=True)
            reply, interrupted = speak_response_stream(response_stream)
            if reply:
                print(console_text(f"[AXIOM] {ASSISTANT_NAME}: {reply}"))
                updated_history = history + [
                    {"role": "user", "text": user_text},
                    {"role": "model", "text": reply},
                ]
                return AIResult(
                    reply=reply,
                    history=_maybe_summarize_history(updated_history),
                    spoke=True,
                    interrupted=interrupted,
                )
            _send("log", {"level": "warn", "text": "Streaming response was empty; retrying normally."})
        except Exception as e:
            print(console_text(f"[AXIOM] Streaming response failed ({e}); retrying normally."))
            _send("log", {"level": "warn", "text": f"Streaming response failed; retrying normally: {e}"})

        chat = model.start_chat(history=gemini_history)

    _send("state", {"state": "thinking"})
    response = chat.send_message(user_text)

    # Tool use loop
    while True:
        parts = _response_parts(response)
        fn_calls = [p for p in parts if getattr(p.function_call, "name", "")]
        if not fn_calls:
            break

        fn_responses = []
        for part in fn_calls:
            fn   = part.function_call
            args = dict(fn.args)
            print(console_text(f"[AXIOM] Tool: {fn.name}({args})"))
            _send("tool",  {"name": fn.name, "input": args})
            _send("state", {"state": "tool"})
            _slow_tool_acknowledgement(fn.name)
            _tools_called.append(fn.name)
            result = clean_text(execute_tool(fn.name, args))
            fn_responses.append(
                genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=fn.name, response={"result": result}
                    )
                )
            )

        _send("state", {"state": "thinking"})
        response = chat.send_message(fn_responses)

    reply = _response_text(response)
    if not reply:
        reply = _retry_empty_spoken_response(chat, response)
    print(console_text(f"[AXIOM] {ASSISTANT_NAME}: {reply}"))

    updated_history = history + [
        {"role": "user",  "text": user_text},
        {"role": "model", "text": reply},
    ]

    # Passive learning — fire and forget, ~25% of turns to conserve API quota
    if random.random() < 0.25:
        threading.Thread(
            target=_passive_learn,
            args=(user_text, reply, CFG),
            daemon=True,
        ).start()

    return AIResult(reply=reply, history=_maybe_summarize_history(updated_history), tools_called=_tools_called)


def _passive_learn(user_text: str, reply: str, cfg: dict) -> None:
    """
    Background: detect new personal facts revealed in this conversation turn
    and silently write them to user-profile.md. Never raises.
    """
    try:
        from user_profile import read_profile
        profile_summary = read_profile(cfg)

        prompt = (
            f'Here is a conversation excerpt:\nUser: "{user_text}"\nAxiom: "{reply}"\n\n'
            f"Here is the current user profile:\n{profile_summary or '(empty)'}\n\n"
            "Did the user reveal any new personal facts not already in the profile? "
            'If yes, return JSON: {"new_facts": [{"category": "...", "key": "...", "value": "..."}]} '
            'If no new facts, return: {"new_facts": []}  JSON only. No explanation.'
        )

        model = genai.GenerativeModel(model_name=cfg["gemini"]["model"])
        response = model.generate_content(prompt)
        raw = response.text.strip()
        raw = __import__("re").sub(r"^```(?:json)?\s*", "", raw)
        raw = __import__("re").sub(r"\s*```$", "", raw)

        parsed = __import__("json").loads(raw)
        new_facts = parsed.get("new_facts", [])

        if new_facts:
            from user_profile import update_profile
            for fact in new_facts:
                cat = fact.get("category", "")
                key = fact.get("key", "")
                val = fact.get("value", "")
                if cat and key and val:
                    update_profile(cat, key, val, cfg)
            print(f"[AXIOM] Passive learning: saved {len(new_facts)} fact(s) to profile")
    except Exception as e:
        print(f"[AXIOM] _passive_learn error: {e}")


def _response_text(response) -> str:
    try:
        return clean_text((response.text or "").strip())
    except Exception:
        parts = []
        for part in _response_parts(response):
            text = getattr(part, "text", "")
            if text:
                parts.append(text)
        if parts:
            return clean_text("\n".join(parts))
        return ""


def _response_finish_reason(response) -> str:
    try:
        reason = getattr(response.candidates[0], "finish_reason", "")
    except Exception:
        return ""
    if not reason:
        return ""

    reason_text = str(reason)
    reason_name = getattr(reason, "name", "") or ""
    reason_value = getattr(reason, "value", None)

    if reason_name and reason_value is not None:
        return f"{reason_name} ({reason_value})"
    if reason_name:
        return reason_name
    return reason_text


def _empty_response_detail(response) -> str:
    finish_reason = _response_finish_reason(response)
    if finish_reason:
        return f"finish reason: {finish_reason}"
    return "no text parts"


def _retry_empty_spoken_response(chat, previous_response) -> str:
    detail = _empty_response_detail(previous_response)
    print(console_text(f"[AXIOM] Gemini returned no spoken text ({detail}); retrying once."))
    _send("log", {"level": "warn", "text": f"Gemini returned no spoken text ({detail}); retrying once."})

    try:
        retry_response = chat.send_message(
            "Please answer the user's last request now in a short, plain spoken response. "
            "Do not call any tools."
        )
        reply = _response_text(retry_response)
        if reply:
            return reply
        retry_detail = _empty_response_detail(retry_response)
        print(console_text(f"[AXIOM] Gemini retry also returned no spoken text ({retry_detail})."))
        _send("log", {"level": "warn", "text": f"Gemini retry also returned no spoken text ({retry_detail})."})
    except Exception as e:
        print(console_text(f"[AXIOM] Gemini empty-response retry failed ({e})."))
        _send("log", {"level": "warn", "text": f"Gemini empty-response retry failed: {e}"})

    return "I had trouble getting Gemini's text back. Could you say that again?"


def _response_parts(response) -> list:
    try:
        parts = list(response.parts or [])
        if parts:
            return parts
    except Exception:
        pass
    try:
        candidates = list(getattr(response, "candidates", []) or [])
        if candidates:
            return list(getattr(candidates[0].content, "parts", []) or [])
    except Exception:
        pass
    return []


def _response_text_delta(response) -> str:
    try:
        return response.text or ""
    except Exception:
        parts = []
        for part in _response_parts(response):
            text = getattr(part, "text", "")
            if text:
                parts.append(text)
        return "".join(parts)


def expects_follow_up(text: str) -> bool:
    """
    Treat direct questions as an invitation to keep listening. Keep this simple
    and conservative so statements do not accidentally hold the mic open.
    """
    cleaned = clean_text(text, collapse_whitespace=True)
    if not cleaned:
        return False
    tail = cleaned[-220:]
    if tail.rstrip().endswith("?"):
        return True
    return bool(re.search(r"\b(do you want|would you like|should i|which one|what do you|what should|how about|can you clarify)\b", tail, re.I))

# ─── TTS ──────────────────────────────────────────────────────────────────────

_speech_interrupt = threading.Event()
_speaking = False
_pyttsx3_engine = None


def _tts_config() -> dict:
    return CFG.get("tts", {}) or {}


def _split_for_tts(text: str) -> list[str]:
    """
    Split long responses into sentence-ish chunks so Edge TTS can start sooner.
    """
    text = clean_text(text)
    if not _tts_config().get("sentence_streaming", True):
        return [text]
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    max_chars = int(_tts_config().get("max_chunk_chars", 150) or 150)
    for part in parts or [text]:
        candidate = f"{current} {part}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks or [text]


def _stream_ready_chunks(buffer: str, final: bool = False) -> tuple[list[str], str]:
    """
    Pull speakable chunks from an incremental text buffer. Prefer complete
    sentences, but release a long clause if Gemini is being punctuation-shy.
    """
    max_chars = int(_tts_config().get("max_chunk_chars", 150) or 150)
    chunks: list[str] = []

    while buffer:
        sentence = re.search(r"(?<=[.!?])\s+", buffer)
        if sentence:
            end = sentence.end()
            chunks.extend(_split_for_tts(buffer[:end].strip()))
            buffer = buffer[end:].lstrip()
            continue

        if len(buffer) >= max_chars * 2:
            split_at = buffer.rfind(" ", 0, max_chars)
            if split_at < max_chars // 2:
                split_at = max_chars
            chunks.append(clean_text(buffer[:split_at].strip()))
            buffer = buffer[split_at:].lstrip()
            continue

        break

    if final and buffer.strip():
        chunks.extend(_split_for_tts(buffer.strip()))
        buffer = ""

    return [chunk for chunk in chunks if chunk], buffer


def _play_tts_queue(chunks: "queue.Queue[Optional[str]]", result: dict) -> None:
    global _speaking
    _speech_interrupt.clear()
    _speaking = True
    _send("state", {"state": "speaking"})
    try:
        while True:
            chunk = chunks.get()
            if chunk is None:
                break
            if _speech_interrupt.is_set():
                result["interrupted"] = True
                break
            if CFG["tts"]["engine"] == "edge":
                interrupted = _speak_edge(chunk)
            else:
                interrupted = _speak_pyttsx3(chunk)
            if interrupted:
                result["interrupted"] = True
                break
    finally:
        _speaking = False
        _send("state", {"state": "idle"})


def speak_response_stream(response_stream) -> tuple[str, bool]:
    """
    Consume a Gemini text stream while a worker speaks completed chunks.
    Returns the full reply text and whether playback was interrupted.
    """
    chunks: queue.Queue[Optional[str]] = queue.Queue()
    result = {"interrupted": False}
    worker = threading.Thread(target=_play_tts_queue, args=(chunks, result), daemon=True)
    worker.start()

    full_text: list[str] = []
    pending = ""
    try:
        for response in response_stream:
            delta = _response_text_delta(response)
            if not delta:
                continue
            full_text.append(delta)
            pending += delta
            ready, pending = _stream_ready_chunks(pending)
            for chunk in ready:
                chunks.put(chunk)
            if result["interrupted"]:
                break

        ready, pending = _stream_ready_chunks(pending, final=True)
        for chunk in ready:
            chunks.put(chunk)
    finally:
        chunks.put(None)
        worker.join()

    reply = clean_text("".join(full_text), collapse_whitespace=True)
    return reply, bool(result["interrupted"])


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
            if not chunk:
                continue
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
        cfg         = _tts_config()
        voice       = cfg.get("edge_voice") or CFG["tts"]["edge_voice"]
        rate        = cfg.get("edge_rate", "+10%")
        volume      = cfg.get("edge_volume", "+0%")
        pitch       = cfg.get("edge_pitch", "+0Hz")
        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
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
    global _pyttsx3_engine
    import pyttsx3
    if _pyttsx3_engine is None:
        _pyttsx3_engine = pyttsx3.init()
    engine = _pyttsx3_engine
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


def reload_runtime_config(new_config: dict):
    """
    Hot-reload mutable runtime config for settings UI saves.
    This avoids reloading Whisper, but refreshes tool config, projects, scenarios,
    voice settings, memory settings, and Gemini model selection.
    """
    global CFG, ASSISTANT_NAME, SAMPLE_RATE, MAX_RECORD_SECS, VAD_THRESHOLD
    global VAD_SILENCE_SECS, MEMORY_FILE, MAX_HISTORY, AUTO_SUMMARIZE_AFTER
    global TTS_ENGINE

    CFG = new_config
    ASSISTANT_NAME = CFG["assistant"]["name"]
    SAMPLE_RATE = CFG["audio"]["sample_rate"]
    MAX_RECORD_SECS = CFG["audio"]["max_record_seconds"]
    VAD_THRESHOLD = CFG["audio"]["vad_energy_threshold"]
    VAD_SILENCE_SECS = CFG["audio"]["vad_silence_duration"]
    MEMORY_FILE = Path(CFG["memory"]["file"])
    MAX_HISTORY = CFG["memory"]["max_history"]
    AUTO_SUMMARIZE_AFTER = CFG.get("memory", {}).get("auto_summarize_after", 20)
    TTS_ENGINE = CFG["tts"]["engine"]

    from tools import reload_config as reload_tools_config
    reload_tools_config(CFG)
    init_scenario_engine()
    _send("config_reloaded", {})
    _send("log", {"level": "system", "text": "Configuration reloaded."})


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
        import warnings
        warnings.filterwarnings("ignore", message=".*pkg_resources.*")
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
