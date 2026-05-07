# AXIOM — Client/Server Architecture
> Split Design: Backend Server + Multi-Device Clients
> Generated: May 2026

---

## Overview

```
┌─────────────────────────────────────────────────────┐
│                   YOUR PC (Backend)                  │
│                                                      │
│  ┌──────────────┐    ┌──────────────┐               │
│  │  Express /   │    │  Obsidian    │               │
│  │  WebSocket   │◄───│  Vault       │               │
│  │  Server      │    │  (local)     │               │
│  └──────┬───────┘    └──────────────┘               │
│         │                                            │
│         │  Gemini API calls, Obsidian reads,        │
│         │  Email/Calendar integrations               │
└─────────┼───────────────────────────────────────────┘
          │  (Tailscale tunnel when remote)
          │
    ┌─────┴──────────────────────────────┐
    │                                    │
┌───▼──────────┐  ┌────────────┐  ┌────▼───────────┐
│  PC 1        │  │  PC 2      │  │  Phone         │
│  Electron    │  │  Electron  │  │  PWA / Browser │
│  Client      │  │  Client    │  │  Client        │
└──────────────┘  └────────────┘  └────────────────┘
```

---

## Folder Structure

```
axiom/
├── server/                    ← Runs on your PC (always)
│   ├── index.js               ← Entry point, Express + WS server
│   ├── gemini.js              ← Gemini API handler (streaming)
│   ├── obsidian.js            ← Vault read/write
│   ├── tts.js                 ← edge-tts handler
│   ├── stt.js                 ← Whisper / faster-whisper
│   ├── calendar.js            ← Calendar integration
│   ├── email.js               ← Email integration
│   └── config.js              ← API keys, vault path, port
│
├── client/                    ← Shared client code
│   ├── electron/              ← Desktop app wrapper
│   │   ├── main.js            ← Electron main process
│   │   └── preload.js         ← IPC bridge
│   ├── pwa/                   ← Phone / browser client
│   │   ├── index.html
│   │   ├── app.js
│   │   └── manifest.json      ← Makes it installable on phone
│   └── shared/
│       ├── ui.js              ← Shared UI components
│       └── socket.js          ← WebSocket client wrapper
│
└── package.json
```

---

## Server: `server/index.js`

```javascript
const express = require('express');
const { WebSocketServer } = require('ws');
const http = require('http');
const path = require('path');
const { handleMessage } = require('./gemini');
const { speak } = require('./tts');
const { transcribe } = require('./stt');

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

const PORT = process.env.PORT || 3737;

// Serve the PWA client (for phone/browser access)
app.use(express.static(path.join(__dirname, '../client/pwa')));

// Health check
app.get('/ping', (req, res) => res.json({ status: 'online', name: 'AXIOM' }));

wss.on('connection', (ws) => {
  console.log('[AXIOM] Client connected');

  ws.on('message', async (data) => {
    const msg = JSON.parse(data);

    // Client sends { type: 'text', content: '...' }
    // or           { type: 'audio', content: <base64 wav> }

    let userText = '';

    if (msg.type === 'audio') {
      // Decode base64 audio and transcribe
      const audioBuffer = Buffer.from(msg.content, 'base64');
      userText = await transcribe(audioBuffer);
      ws.send(JSON.stringify({ type: 'transcript', content: userText }));
    } else {
      userText = msg.content;
    }

    if (!userText.trim()) return;

    // Stream Gemini response back to client
    ws.send(JSON.stringify({ type: 'thinking' }));

    await handleMessage(userText, (chunk) => {
      // Send each text chunk to client as it streams
      ws.send(JSON.stringify({ type: 'chunk', content: chunk }));
    }, (fullResponse) => {
      // Send complete signal when done
      ws.send(JSON.stringify({ type: 'done', content: fullResponse }));
    });
  });

  ws.on('close', () => console.log('[AXIOM] Client disconnected'));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`[AXIOM] Backend running on port ${PORT}`);
});
```

---

## Server: `server/gemini.js`

```javascript
const { GoogleGenerativeAI } = require('@google/generative-ai');
const { readVaultContext } = require('./obsidian');
const config = require('./config');

const genAI = new GoogleGenerativeAI(config.GEMINI_API_KEY);
const model = genAI.getGenerativeModel({ model: 'gemini-1.5-flash' });

// Conversation history per session (in production, key by ws client id)
const history = [];

async function handleMessage(userText, onChunk, onDone) {
  // Pull relevant Obsidian context
  const vaultContext = await readVaultContext(userText);

  const systemPrompt = `You are AXIOM, a personal AI assistant.
You have access to the user's second brain (Obsidian notes).
Relevant notes context:
${vaultContext}
Be concise. Respond naturally as if speaking aloud.`;

  history.push({ role: 'user', parts: [{ text: userText }] });

  const chat = model.startChat({
    history: history.slice(0, -1), // all but last
    systemInstruction: systemPrompt,
  });

  const result = await chat.sendMessageStream(userText);

  let fullResponse = '';
  let buffer = '';

  for await (const chunk of result.stream) {
    const text = chunk.text();
    fullResponse += text;
    buffer += text;

    // Send chunks to client
    onChunk(text);

    // Optionally detect sentence boundaries for TTS on server side
    // (if doing server-side TTS)
  }

  history.push({ role: 'model', parts: [{ text: fullResponse }] });
  onDone(fullResponse);
}

module.exports = { handleMessage };
```

---

## Server: `server/obsidian.js`

```javascript
const fs = require('fs');
const path = require('path');
const config = require('./config');

// Simple keyword search across vault markdown files
async function readVaultContext(query) {
  const vaultPath = config.OBSIDIAN_VAULT_PATH;
  if (!vaultPath || !fs.existsSync(vaultPath)) return '';

  const keywords = query.toLowerCase().split(' ').filter(w => w.length > 3);
  const results = [];

  function searchDir(dir) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith('.')) {
        searchDir(fullPath);
      } else if (entry.name.endsWith('.md')) {
        const content = fs.readFileSync(fullPath, 'utf-8');
        const lower = content.toLowerCase();
        const score = keywords.filter(k => lower.includes(k)).length;
        if (score > 0) {
          results.push({ path: fullPath, content, score });
        }
      }
    }
  }

  searchDir(vaultPath);
  results.sort((a, b) => b.score - a.score);

  // Return top 3 most relevant notes, trimmed
  return results
    .slice(0, 3)
    .map(r => `## ${path.basename(r.path, '.md')}\n${r.content.slice(0, 800)}`)
    .join('\n\n---\n\n');
}

async function writeNote(title, content, folder = 'AXIOM') {
  const vaultPath = config.OBSIDIAN_VAULT_PATH;
  const targetDir = path.join(vaultPath, folder);
  if (!fs.existsSync(targetDir)) fs.mkdirSync(targetDir, { recursive: true });
  const filePath = path.join(targetDir, `${title}.md`);
  fs.writeFileSync(filePath, content, 'utf-8');
  return filePath;
}

module.exports = { readVaultContext, writeNote };
```

---

## Server: `server/config.js`

```javascript
module.exports = {
  GEMINI_API_KEY: process.env.GEMINI_API_KEY || 'your-key-here',
  OBSIDIAN_VAULT_PATH: process.env.OBSIDIAN_VAULT_PATH || 'C:/Users/YOU/Documents/ObsidianVault',
  PORT: process.env.PORT || 3737,
};
```

---

## Client: `client/shared/socket.js`

```javascript
// Shared WebSocket client — used by both Electron and PWA

class AxiomSocket {
  constructor(serverUrl) {
    this.url = serverUrl;
    this.ws = null;
    this.onTranscript = null;
    this.onChunk = null;
    this.onDone = null;
    this.onThinking = null;
  }

  connect() {
    this.ws = new WebSocket(this.url);

    this.ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'transcript' && this.onTranscript) this.onTranscript(msg.content);
      if (msg.type === 'chunk' && this.onChunk) this.onChunk(msg.content);
      if (msg.type === 'done' && this.onDone) this.onDone(msg.content);
      if (msg.type === 'thinking' && this.onThinking) this.onThinking();
    };

    this.ws.onopen = () => console.log('[AXIOM] Connected to backend');
    this.ws.onclose = () => setTimeout(() => this.connect(), 3000); // auto-reconnect
  }

  sendAudio(base64Audio) {
    this.ws.send(JSON.stringify({ type: 'audio', content: base64Audio }));
  }

  sendText(text) {
    this.ws.send(JSON.stringify({ type: 'text', content: text }));
  }
}

// Auto-detect server URL
// In Electron: use env variable set by main process
// In PWA: use same host as page (so phone connects to your PC)
const SERVER_URL = window.AXIOM_SERVER || `ws://${location.hostname}:3737`;

const axiomSocket = new AxiomSocket(SERVER_URL);
axiomSocket.connect();

export default axiomSocket;
```

---

## Auto-Start on Boot (Windows)

Save as `start-axiom.bat` and add to Windows Startup folder (`shell:startup`):

```batch
@echo off
cd /d C:\path\to\axiom
node server/index.js
```

Or use **PM2** (recommended — handles crashes, auto-restart):

```bash
npm install -g pm2
pm2 start server/index.js --name axiom
pm2 startup   # makes it survive reboots
pm2 save
```

---

## Remote Access with Tailscale

1. Install Tailscale on your PC and phone/laptop: https://tailscale.com
2. Sign in on both devices (free account)
3. On your phone, connect to Axiom at `ws://YOUR-PC-TAILSCALE-IP:3737`
4. That's it — works anywhere, fully encrypted

---

## PWA Install on Phone

Once the server is running, visit `http://YOUR-PC-IP:3737` on your phone browser.
Chrome/Safari will offer "Add to Home Screen" — this installs it as an app icon.
Add to `client/pwa/manifest.json`:

```json
{
  "name": "AXIOM",
  "short_name": "AXIOM",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#03050e",
  "theme_color": "#00d4ff",
  "icons": [
    { "src": "icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

---

## Migration Steps (from current single-app to client/server)

1. `npm init` a new `axiom/` monorepo
2. Move Gemini logic → `server/gemini.js`
3. Move Obsidian logic → `server/obsidian.js`
4. Create `server/index.js` WebSocket server
5. Strip Electron app to just mic + WebSocket client
6. Copy client UI into `client/pwa/` for phone access
7. Set up PM2 for auto-start
8. Install Tailscale for remote access

---

*AXIOM Architecture v2.0 — Multi-device client/server split*
