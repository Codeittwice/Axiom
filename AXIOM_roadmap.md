# AXIOM — Tool Ideas & Roadmap

> All ideas for tools, integrations, and features.
> Update status as things get implemented.

---

## Status Key
- ✅ Implemented
- 🔨 In progress
- 📋 Planned
- 💡 Idea
- ❌ Requires paid service

---

## Productivity

| Tool | Phrase example | Status | Notes |
|---|---|---|---|
| Create Obsidian note | "Save a note about async Python" | ✅ | Writes .md to vault |
| Read Obsidian note | "Read my note about async Python" | ✅ | Reads .md from vault |
| Append to daily note | "Add to today's note: standup at 10" | ✅ | Appends to YYYY-MM-DD.md |
| Search Obsidian vault | "Search my notes for Docker" | ✅ | Recursive grep through .md files |
| Set a timer | "Set a 25-minute Pomodoro timer" | ✅ | Windows notification on completion |
| Read clipboard | "What's in my clipboard?" | ✅ | Via pyperclip |
| Write to clipboard | "Copy that to clipboard" | ✅ | Via pyperclip |
| Calendar — read events | "What's on my calendar today?" | 📋 | Google Calendar API (free OAuth) |
| Calendar — create event | "Add meeting Thursday at 3pm" | 📋 | Google Calendar API (free OAuth) |
| Reminders | "Remind me at 5pm to close Jira" | 💡 | Scheduled threading.Timer + notification |
| Email — read | "Any emails from John?" | 💡 | Gmail API (free OAuth) |
| Email — send | "Email John: running late" | 💡 | Gmail API (free OAuth) |

---

## Developer Tools

| Tool | Phrase example | Status | Notes |
|---|---|---|---|
| Open repo in VS Code | "Open the axiom repo" | ✅ | Path mapped in config.yaml |
| Git status | "Git status on axiom" | ✅ | Runs git in repo dir |
| Git pull | "Pull latest on axiom" | ✅ | Runs `git pull` |
| Git commit | "Commit all changes: fixed VAD bug" | ✅ | `git add -A && git commit -m` |
| Git log | "Show last 5 commits on axiom" | ✅ | `git log --oneline -5` |
| Run terminal command | "Run the tests" / "npm install" | ✅ | Subprocess, sandboxed to repo |
| Describe screen | "What's on my screen?" | ✅ | Screenshot → Gemini vision |
| Create a file | "Create utils.py in axiom" | 💡 | Write file at path |
| Search in codebase | "Find where I handle errors" | 💡 | Recursive grep through repo |
| Open GitHub PR | "Open the latest PR for axiom" | 💡 | `gh` CLI or GitHub API |
| Run build | "Build the project" | 💡 | Configurable build command per repo |
| Docker commands | "Start the docker containers" | 💡 | `docker-compose up` etc. |
| Check port usage | "What's running on port 3000?" | 💡 | `netstat` |

---

## Media & Entertainment

| Tool | Phrase example | Status | Notes |
|---|---|---|---|
| System volume | "Turn volume to 40" / "Mute" | ✅ | pycaw (Windows) |
| Spotify — play | "Play lo-fi hip hop" | 📋 | spotipy, free Spotify dev account |
| Spotify — control | "Skip" / "Pause" / "Volume up" | 📋 | spotipy |
| YouTube search | "Play Interstellar soundtrack on YouTube" | 💡 | Opens browser with search URL |
| Local media | "Play music from my downloads" | 💡 | pygame / vlc subprocess |

---

## Information & Knowledge

| Tool | Phrase example | Status | Notes |
|---|---|---|---|
| Web search | "What's in the news today?" | ✅ | DuckDuckGo, no API key |
| Weather | "Weather in London?" | ✅ | wttr.in, no API key |
| Date/time | "What time is it?" | ✅ | Local system |
| Wikipedia | "Who is Alan Turing?" | ✅ | wikipedia package |
| Currency convert | "100 USD to EUR?" | 💡 | exchangerate-api.com free tier |
| Stock / crypto price | "What's Bitcoin at?" | 💡 | yfinance (free) |
| News headlines | "Top tech news today" | 💡 | NewsAPI free tier (100 req/day) |
| Word definition | "Define ephemeral" | 💡 | Free dictionary API |
| Math / calculator | "What's 15% of 340?" | 💡 | Gemini handles this natively |
| Unit conversion | "30 miles in km?" | 💡 | Gemini handles this natively |

---

## System Control (Windows)

| Tool | Phrase example | Status | Notes |
|---|---|---|---|
| Open app | "Open Notepad" / "Open Chrome" | ✅ | subprocess |
| Open website | "Open GitHub" / "Open my email" | ✅ | webbrowser |
| System volume | "Set volume to 50" | ✅ | pycaw |
| Describe screen | "What's on my screen?" | ✅ | Pillow screenshot + Gemini |
| Screenshot save | "Take a screenshot" | 💡 | PIL.ImageGrab → file |
| Lock screen | "Lock my PC" | 💡 | `ctypes.windll.user32.LockWorkStation()` |
| Shutdown / restart | "Restart in 10 minutes" | 💡 | `shutdown /r /t 600` |
| Clipboard | "Copy that" / "What's in clipboard?" | ✅ | pyperclip |
| List running apps | "What's using my CPU?" | 💡 | psutil |
| Kill process | "Kill Chrome" | 💡 | psutil — needs confirmation safeguard |
| Battery status | "How's my battery?" | 💡 | psutil |
| Disk space | "How much space do I have?" | 💡 | shutil.disk_usage |
| Brightness | "Dim the screen" | 💡 | screen-brightness-control package |

---

## Communication & Smart Home

| Tool | Phrase example | Status | Notes |
|---|---|---|---|
| Send Slack message | "Message #general: be right back" | 💡 | Slack SDK (free bot token) |
| Smart lights | "Turn off the lights" | 💡 | Philips Hue API / Home Assistant |
| Smart plugs | "Turn on the desk fan" | 💡 | Home Assistant |
| WhatsApp | "Message mom: on my way" | 💡 | Requires unofficial API or Twilio |

---

## Obsidian-specific Power Features

| Feature | Description | Status |
|---|---|---|
| Voice to daily note | Auto-log all AXIOM sessions to today's daily note | 💡 |
| AXIOM log template | Prepend a template header to each session note | 💡 |
| Inline note tagging | Tag notes with `#axiom` automatically | 💡 |
| Vault search + summarise | Find and summarise all notes on a topic | 💡 |
| Note → flashcards | "Make flashcards from my async Python note" | 💡 |

---

## AI Enhancements

| Feature | Description | Status |
|---|---|---|
| Vision (describe screen) | Screenshot → Gemini vision | ✅ |
| Memory across sessions | Persistent conversation history | ✅ |
| Custom wake word "Hey Axiom" | Train model at github.com/dscripka/openWakeWord | 📋 |
| Per-app personality | Different tone for coding vs relaxing | 💡 |
| Voice emotion detection | Detect stress/urgency in voice | 💡 |
| Proactive reminders | AXIOM speaks unprompted at set times | 💡 |
| Summarise clipboard | "Summarise what I just copied" | 💡 |
| Code explanation | "Explain the code on my screen" | 💡 Combine screen + Gemini |

---

## Setup Complexity Guide

| Difficulty | Requirement |
|---|---|
| 🟢 Easy | Just pip install + config |
| 🟡 Medium | Free API key or OAuth setup (~15 min) |
| 🔴 Hard | Paid service, hardware, or complex config |

| Tool group | Difficulty |
|---|---|
| All ✅ already implemented | 🟢 |
| Spotify | 🟡 Free Spotify dev account + `spotipy` |
| Google Calendar / Gmail | 🟡 Free Google OAuth credentials |
| Slack | 🟡 Free Slack bot token |
| Custom "Hey Axiom" wake word | 🟡 Training script, ~30 min |
| News headlines | 🟡 Free NewsAPI key |
| Smart home | 🔴 Requires Hue hub or Home Assistant |
