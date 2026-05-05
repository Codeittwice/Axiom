const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const APP_PORT = Number(process.env.AXIOM_PORT || 5000);
const APP_URL = `http://127.0.0.1:${APP_PORT}`;
const ROOT_DIR = path.join(__dirname, '..');
const ICON_PATH = path.join(__dirname, 'build', 'icon.ico');

let pythonProc = null;
let mainWindow = null;
let tray = null;
let isQuitting = false;

function iconImage() {
  const image = nativeImage.createFromPath(ICON_PATH);
  return image.isEmpty() ? undefined : image;
}

function backendCommand() {
  const packagedBackend = path.join(process.resourcesPath || '', 'axiom_backend.exe');
  if (app.isPackaged && fs.existsSync(packagedBackend)) {
    return { command: packagedBackend, args: [], cwd: path.dirname(packagedBackend) };
  }

  return {
    command: process.env.AXIOM_PYTHON || 'python',
    args: ['server.py'],
    cwd: ROOT_DIR,
  };
}

function startPython() {
  if (pythonProc) return;

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

function createWindow(startMinimized = false) {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 1040,
    minWidth: 760,
    minHeight: 760,
    show: !startMinimized,
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

function bindIpc() {
  ipcMain.handle('window:minimize', () => mainWindow?.minimize());
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
