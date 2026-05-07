const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const APP_PORT = Number(process.env.AXIOM_PORT || 5000);
const APP_URL = `http://127.0.0.1:${APP_PORT}`;
const ROOT_DIR = path.join(__dirname, '..');
const DEV_USER_DATA = path.join(ROOT_DIR, '.axiom-user-data');
const ICON_PATH = path.join(__dirname, 'build', 'icon.ico');

if (!app.isPackaged) {
  app.setPath('userData', DEV_USER_DATA);
}

let pythonProc = null;
let mainWindow = null;
let tray = null;
let isQuitting = false;
let quickCrashCount = 0;

function iconImage() {
  const image = nativeImage.createFromPath(ICON_PATH);
  return image.isEmpty() ? undefined : image;
}

function backendCommand() {
  const packagedBackend = path.join(process.resourcesPath || '', 'axiom_backend.exe');
  if (app.isPackaged && fs.existsSync(packagedBackend)) {
    return { command: packagedBackend, args: [], cwd: path.dirname(packagedBackend) };
  }

  // Auto-detect venv — prefer .venv/Scripts/python.exe if it exists
  const venvPython = path.join(ROOT_DIR, '.venv', 'Scripts', 'python.exe');
  const pythonCmd = process.env.AXIOM_PYTHON ||
    (fs.existsSync(venvPython) ? venvPython : 'python');

  return {
    command: pythonCmd,
    args: ['server.py'],
    cwd: ROOT_DIR,
  };
}

function startPython() {
  if (pythonProc) return;

  const startedAt = Date.now();
  const backend = backendCommand();
  pythonProc = spawn(backend.command, backend.args, {
    cwd: backend.cwd,
    detached: false,
    windowsHide: true,
    env: {
      ...process.env,
      AXIOM_ELECTRON: '1',
      AXIOM_PORT: String(APP_PORT),
    },
  });

  pythonProc.stdout?.on('data', data => console.log(`[axiom-backend] ${data}`));
  pythonProc.stderr?.on('data', data => console.error(`[axiom-backend] ${data}`));
  pythonProc.on('exit', (code, signal) => {
    console.log(`[axiom-backend] exited code=${code} signal=${signal}`);
    pythonProc = null;
    if (!isQuitting) {
      quickCrashCount = Date.now() - startedAt < 5000 ? quickCrashCount + 1 : 0;
      if (quickCrashCount >= 5) {
        console.error('[axiom-backend] stopped after 5 quick crashes. Fix the backend error and restart AXIOM.');
        return;
      }
      setTimeout(startPython, 1500);
    }
  });
}

function stopPython() {
  if (!pythonProc) return;
  const proc = pythonProc;
  pythonProc = null;
  proc.kill();
}

function waitForServer(timeoutMs = 30000) {
  const start = Date.now();

  return new Promise((resolve, reject) => {
    const ping = () => {
      const req = http.get(APP_URL, res => {
        res.resume();
        resolve();
      });
      req.on('error', () => {
        if (Date.now() - start > timeoutMs) {
          reject(new Error(`Timed out waiting for ${APP_URL}`));
          return;
        }
        setTimeout(ping, 250);
      });
      req.setTimeout(1000, () => req.destroy());
    };
    ping();
  });
}

let splashWindow = null;

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 500,
    height: 560,
    frame: false,
    alwaysOnTop: true,
    resizable: false,
    backgroundColor: '#03050e',
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  splashWindow.center();
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close();
    splashWindow = null;
  }
}

function createWindow(startMinimized = false) {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 1040,
    minWidth: 960,
    minHeight: 760,
    show: false,   // revealed after splash closes
    frame: false,
    backgroundColor: '#03050e',
    icon: ICON_PATH,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadURL(APP_URL);

  mainWindow.once('ready-to-show', () => {
    closeSplash();
    if (!startMinimized) mainWindow.show();
  });

  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.type === 'keyDown' && input.key === 'F11') {
      event.preventDefault();
      toggleFullscreen();
    }
  });

  mainWindow.on('enter-full-screen', () => {
    mainWindow?.webContents.send('window:fullscreen-changed', true);
  });
  mainWindow.on('leave-full-screen', () => {
    mainWindow?.webContents.send('window:fullscreen-changed', false);
  });

  mainWindow.on('close', event => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow.hide();
  });
}

function createTray() {
  const image = iconImage();
  if (!image) return;

  tray = new Tray(image);
  tray.setToolTip('AXIOM Voice Assistant');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open AXIOM', click: () => mainWindow?.show() },
    { label: 'Toggle Fullscreen', click: () => toggleFullscreen() },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]));
  tray.on('double-click', () => mainWindow?.show());
}

function toggleFullscreen() {
  if (!mainWindow) return false;
  const next = !mainWindow.isFullScreen();
  mainWindow.setFullScreen(next);
  return next;
}

function bindIpc() {
  ipcMain.handle('window:minimize', () => mainWindow?.minimize());
  ipcMain.handle('window:toggle-fullscreen', () => toggleFullscreen());
  ipcMain.handle('window:close', () => mainWindow?.hide());
  ipcMain.handle('window:quit', () => {
    isQuitting = true;
    app.quit();
  });
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    bindIpc();
    app.setLoginItemSettings({
      openAtLogin: true,
      args: ['--minimized'],
    });

    const startMinimized = process.argv.includes('--minimized');
    startPython();
    createSplash();
    await waitForServer();
    createWindow(startMinimized);
    createTray();
  });
}

app.on('activate', () => {
  if (mainWindow) {
    mainWindow.show();
    return;
  }
  createWindow(false);
});

app.on('before-quit', () => {
  isQuitting = true;
  stopPython();
});
