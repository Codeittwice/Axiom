"""
AXIOM Question Engine — proactive user profiling via structured Q&A.

Drives three modes:
  - Onboarding: focused session asking questions until profile is reasonably complete
  - Passive: pick the single highest-priority unanswered question and ask it
  - Weekly check-in: triggered externally once a week

Gemini parses answers to extract structured facts → user_profile.py writes them.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from typing import Callable, Optional

# ─── Question bank (26 questions, ordered by priority) ────────────────────────

QUESTION_BANK: list[dict] = [
    # Identity
    {"id": 1,  "text": "What's your name?",
     "category": "Identity", "profile_key": ("Identity", "Name")},
    {"id": 2,  "text": "How old are you, roughly — or what decade are you in?",
     "category": "Identity", "profile_key": ("Identity", "Age range")},
    {"id": 3,  "text": "Where are you based?",
     "category": "Identity", "profile_key": ("Identity", "Location")},
    {"id": 4,  "text": "What languages do you speak?",
     "category": "Identity", "profile_key": ("Identity", "Languages")},
    {"id": 5,  "text": "What pronouns do you use?",
     "category": "Identity", "profile_key": ("Identity", "Pronouns")},
    # Work & Career
    {"id": 6,  "text": "What do you do for work or study?",
     "category": "Work & Career", "profile_key": ("Work & Career", "Job / field")},
    {"id": 7,  "text": "What industry or field are you in?",
     "category": "Work & Career", "profile_key": ("Work & Career", "Industry")},
    {"id": 8,  "text": "Do you prefer working solo, collaboratively, or a mix of both?",
     "category": "Work & Career", "profile_key": ("Work & Career", "Work style")},
    {"id": 9,  "text": "What's your biggest work or study goal right now?",
     "category": "Work & Career", "profile_key": ("Work & Career", "Current goal")},
    # Daily Life
    {"id": 10, "text": "Are you a morning person or more of a night owl?",
     "category": "Daily Life", "profile_key": ("Daily Life", "Morning or night person")},
    {"id": 11, "text": "How structured is your typical day — very planned or more go-with-the-flow?",
     "category": "Daily Life", "profile_key": ("Daily Life", "Schedule structure")},
    {"id": 12, "text": "When do you feel most focused and productive?",
     "category": "Daily Life", "profile_key": ("Daily Life", "Peak energy time")},
    {"id": 13, "text": "How do you mainly use me day to day — reminders, research, coding help, something else?",
     "category": "Daily Life", "profile_key": ("Daily Life", "Main uses for Axiom")},
    # Interests & Hobbies
    {"id": 14, "text": "What do you enjoy doing in your free time?",
     "category": "Interests & Hobbies", "profile_key": ("Interests & Hobbies", "Hobbies")},
    {"id": 15, "text": "What topics could you talk about endlessly?",
     "category": "Interests & Hobbies", "profile_key": ("Interests & Hobbies", "Favourite topics")},
    {"id": 16, "text": "What kind of media do you consume most — podcasts, YouTube, books, social media?",
     "category": "Interests & Hobbies", "profile_key": ("Interests & Hobbies", "Media habits")},
    {"id": 17, "text": "How do you prefer to learn new things — by doing, reading, watching, or discussing?",
     "category": "Interests & Hobbies", "profile_key": ("Interests & Hobbies", "How they learn")},
    # Personality & Mindset
    {"id": 18, "text": "How do you usually make decisions — logic and data, gut feeling, or something else?",
     "category": "Personality & Mindset", "profile_key": ("Personality & Mindset", "Decision style")},
    {"id": 19, "text": "How would you describe your social energy — introvert, extrovert, or somewhere in between?",
     "category": "Personality & Mindset", "profile_key": ("Personality & Mindset", "Social energy")},
    {"id": 20, "text": "What tends to stress you out the most?",
     "category": "Personality & Mindset", "profile_key": ("Personality & Mindset", "Stress triggers")},
    {"id": 21, "text": "What motivates you most — growth, freedom, purpose, challenge, or something else?",
     "category": "Personality & Mindset", "profile_key": ("Personality & Mindset", "Motivators")},
    # Axiom Preferences
    {"id": 22, "text": "What tone do you prefer from me — casual, professional, witty, calm, or direct?",
     "category": "Axiom Preferences", "profile_key": ("Axiom Preferences", "Preferred tone")},
    {"id": 23, "text": "How much detail do you want in answers — short and punchy, some context, or deep dives?",
     "category": "Axiom Preferences", "profile_key": ("Axiom Preferences", "Answer detail level")},
    {"id": 24, "text": "Should I push back and challenge you sometimes, or just focus on helping?",
     "category": "Axiom Preferences", "profile_key": ("Axiom Preferences", "Should Axiom challenge them")},
    {"id": 25, "text": "What's the most important thing you'd want me to always remember about you?",
     "category": "Axiom Preferences", "profile_key": ("Axiom Preferences", "Preferred tone")},
    {"id": 26, "text": "Is there anything you'd never want me to bring up or ask about?",
     "category": "Axiom Preferences", "profile_key": ("Axiom Preferences", "Should Axiom challenge them")},
]

# ─── Globals ──────────────────────────────────────────────────────────────────

_onboarding_active = False
_onboarding_lock = threading.Lock()

# ─── Core logic ───────────────────────────────────────────────────────────────

def get_next_question(cfg: dict) -> Optional[dict]:
    """
    Return the highest-priority unanswered question from the bank, or None if all answered.
    """
    from user_profile import has_info
    for q in QUESTION_BANK:
        category, key = q["profile_key"]
        if not has_info(key, cfg):
            return q
    return None


def parse_answer(question_text: str, answer_text: str, cfg: dict) -> dict:
    """
    Call Gemini to extract structured facts from a Q&A exchange.
    Returns {"facts": [...], "inferred_traits": [...], "follow_up_topics": [...]}
    or an empty structure on failure.
    """
    import google.generativeai as genai
    import yaml

    empty = {"facts": [], "inferred_traits": [], "follow_up_topics": []}
    try:
        with open("config.yaml") as f:
            _cfg = yaml.safe_load(f)
        model_name = _cfg.get("gemini", {}).get("model", "gemini-2.5-flash")
        genai.configure(api_key=_cfg.get("gemini", {}).get("api_key") or __import__("os").environ.get("GEMINI_API_KEY", ""))

        prompt = (
            f'The user was asked: "{question_text}"\n'
            f'The user answered: "{answer_text}"\n\n'
            "Extract structured facts from this answer and return JSON only. Format:\n"
            '{\n'
            '  "facts": [\n'
            '    { "category": "Identity", "key": "Name", "value": "Hristo" }\n'
            '  ],\n'
            '  "inferred_traits": ["prefers working independently"],\n'
            '  "follow_up_topics": ["what kind of projects they work on"]\n'
            '}\n'
            "Return JSON only. No preamble, no explanation, no markdown fences."
        )
        model = genai.GenerativeModel(model_name=model_name)
        response = model.generate_content(prompt)
        raw = response.text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        return {
            "facts": parsed.get("facts", []),
            "inferred_traits": parsed.get("inferred_traits", []),
            "follow_up_topics": parsed.get("follow_up_topics", []),
        }
    except Exception as e:
        print(f"[AXIOM] question_engine parse_answer error: {e}")
        return empty


def write_parsed_facts(parsed: dict, cfg: dict) -> None:
    """
    Write extracted facts, inferred traits, and follow-up topics to user-profile.md.
    Never raises.
    """
    from user_profile import update_profile, append_inferred_trait, append_open_question
    try:
        for fact in parsed.get("facts", []):
            cat = fact.get("category", "")
            key = fact.get("key", "")
            val = fact.get("value", "")
            if cat and key and val:
                update_profile(cat, key, val, cfg)
        for trait in parsed.get("inferred_traits", []):
            if trait:
                append_inferred_trait(trait, cfg)
        for topic in parsed.get("follow_up_topics", []):
            if topic:
                append_open_question(topic, cfg)
    except Exception as e:
        print(f"[AXIOM] write_parsed_facts error: {e}")


# ─── Onboarding session ───────────────────────────────────────────────────────

def run_onboarding(
    cfg: dict,
    speak_fn: Callable[[str], None],
    record_fn: Callable[[], Optional[str]],
    transcribe_fn: Callable[[str], str],
) -> None:
    """
    Run a full onboarding session: ask questions until the profile is reasonably
    complete (fewer than 10 missing fields) or the user stops responding.

    Designed to run in a background daemon thread — never blocks the main loop.
    Never raises.
    """
    global _onboarding_active
    with _onboarding_lock:
        if _onboarding_active:
            return
        _onboarding_active = True

    try:
        speak_fn(
            "Let's take a minute to set up your profile so I can get to know you better. "
            "I'll ask you a few questions — just answer naturally."
        )
        time.sleep(0.5)

        max_questions = 26
        asked = 0
        consecutive_failures = 0

        while asked < max_questions and consecutive_failures < 3:
            q = get_next_question(cfg)
            if q is None:
                speak_fn("I think I know you pretty well now. Profile's all set.")
                break

            speak_fn(q["text"])
            time.sleep(0.3)

            audio_path = record_fn()
            if not audio_path:
                consecutive_failures += 1
                continue

            answer = transcribe_fn(audio_path).strip()
            if not answer or len(answer.split()) < 2:
                consecutive_failures += 1
                speak_fn("I didn't catch that. Let's move on.")
                continue

            consecutive_failures = 0
            parsed = parse_answer(q["text"], answer, cfg)
            write_parsed_facts(parsed, cfg)

            # If Gemini didn't extract the direct answer, write it ourselves
            cat, key = q["profile_key"]
            from user_profile import has_info
            if not has_info(key, cfg):
                from user_profile import update_profile
                update_profile(cat, key, answer, cfg)

            asked += 1
            from user_profile import get_missing_topics
            if len(get_missing_topics(cfg)) < 10:
                speak_fn("Great, I've got a solid picture of you now. We can always add more later.")
                break
            time.sleep(1.0)

        print(f"[AXIOM] Onboarding complete — {asked} questions asked")
    except Exception as e:
        print(f"[AXIOM] run_onboarding error: {e}")
    finally:
        with _onboarding_lock:
            _onboarding_active = False


def ask_one_question(
    cfg: dict,
    speak_fn: Callable[[str], None],
    record_fn: Callable[[], Optional[str]],
    transcribe_fn: Callable[[str], str],
) -> None:
    """
    Ask a single unanswered question (passive / on-demand mode).
    Runs in a background daemon thread. Never raises.
    """
    global _onboarding_active
    with _onboarding_lock:
        if _onboarding_active:
            return

    try:
        q = get_next_question(cfg)
        if q is None:
            speak_fn("Actually, I think I already know everything important about you.")
            return

        speak_fn(q["text"])
        time.sleep(0.3)

        audio_path = record_fn()
        if not audio_path:
            return

        answer = transcribe_fn(audio_path).strip()
        if not answer or len(answer.split()) < 2:
            return

        parsed = parse_answer(q["text"], answer, cfg)
        write_parsed_facts(parsed, cfg)

        cat, key = q["profile_key"]
        from user_profile import has_info, update_profile
        if not has_info(key, cfg):
            update_profile(cat, key, answer, cfg)

    except Exception as e:
        print(f"[AXIOM] ask_one_question error: {e}")


def read_profile_summary(cfg: dict) -> str:
    """Return a spoken-friendly summary of the user profile."""
    from user_profile import read_profile, get_missing_topics
    profile = read_profile(cfg)
    if not profile:
        return "I don't know much about you yet. Try saying 'let's do onboarding' and I'll ask you a few questions."
    missing = get_missing_topics(cfg)
    suffix = ""
    if missing:
        suffix = f" There are still {len(missing)} things I'd love to learn about you."
    # Strip markdown formatting for voice
    spoken = re.sub(r"##\s*", "", profile)
    spoken = re.sub(r"-\s+", "", spoken)
    spoken = re.sub(r"\*+", "", spoken)
    spoken = re.sub(r"\n{2,}", ". ", spoken)
    spoken = re.sub(r"\n", ", ", spoken)
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return f"Here's what I know about you. {spoken}{suffix}"
