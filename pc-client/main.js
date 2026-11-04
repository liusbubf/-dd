/**
 * X86 云手机平台 —— PC 群控客户端（Electron 主进程）
 *
 * 形态对齐魔云腾 Windows 客户端：本客户端是对 Web 管理端（frontend/，Vue + Vite）
 * 的桌面封装，三端（Web / PC / App）复用同一套 FastAPI 后端 API，数据天然一致（计划 D17）。
 *
 * 加载策略：
 *   1. 开发模式：ELECTRON_START_URL 指向 Vite dev server（默认 http://localhost:5173）
 *   2. 打包模式：加载随安装包分发的前端构建产物（resources/frontend/index.html）
 *   3. 未打包但已构建：直接加载 ../frontend/dist/index.html
 */
const { app, BrowserWindow, Menu, shell, ipcMain, dialog } = require('electron');
const path = require('path');
const fs = require('fs');

// Vite dev server 地址（npm run dev 通过 cross-env 注入）
const DEV_URL = process.env.ELECTRON_START_URL || '';
const DEFAULT_DEV_URL = 'http://localhost:5173';

/** @type {BrowserWindow | null} */
let mainWindow = null;

/** 解析打包/未打包两种情况下的前端构建产物路径 */
function resolveFrontendIndex() {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, 'frontend', 'index.html')]
    : [path.join(__dirname, '..', 'frontend', 'dist', 'index.html')];
  return candidates.find((p) => fs.existsSync(p)) || null;
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: '云手机群控客户端',
    show: false, // ready-to-show 后再显示，避免白屏闪烁
    autoHideMenuBar: false,
    webPreferences: {
      // 安全基线：渲染进程不开 Node 集成，走 preload 桥
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow && mainWindow.show());

  // 外链（如指纹检测网站、目标网页）交给系统浏览器，客户端窗口只承载管理台
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  // ---- 选择加载来源 ----
  if (DEV_URL) {
    mainWindow.loadURL(DEV_URL);
  } else {
    const indexHtml = resolveFrontendIndex();
    if (indexHtml) {
      mainWindow.loadFile(indexHtml);
    } else if (!app.isPackaged) {
      // 开发机上没有 dist 时，兜底连 Vite dev server
      mainWindow.loadURL(DEFAULT_DEV_URL);
    } else {
      dialog.showErrorBox(
        '前端资源缺失',
        '未找到 Web 管理端构建产物（frontend/dist）。\n请先在 frontend/ 目录执行 npm run build 后重新打包。'
      );
      app.quit();
      return;
    }
  }

  // 开发模式下自动开 DevTools，方便联调
  if (DEV_URL) mainWindow.webContents.openDevTools({ mode: 'detach' });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/** 原生应用菜单（中文，对齐桌面客户端形态） */
function buildMenu() {
  const isMac = process.platform === 'darwin';
  /** @type {Electron.MenuItemConstructorOptions[]} */
  const template = [
    ...(isMac
      ? [{ label: app.name, submenu: [{ role: 'about', label: '关于云手机群控客户端' }, { type: 'separator' }, { role: 'quit', label: '退出' }] }]
      : []),
    {
      label: '客户端',
      submenu: [
        {
          label: '回到控制台首页',
          accelerator: 'CmdOrCtrl+H',
          click: () => {
            if (!mainWindow) return;
            if (DEV_URL) mainWindow.loadURL(DEV_URL);
            else {
              const indexHtml = resolveFrontendIndex();
              if (indexHtml) mainWindow.loadFile(indexHtml);
            }
          },
        },
        { role: 'reload', label: '刷新' },
        { role: 'forceReload', label: '强制刷新' },
        { type: 'separator' },
        isMac ? { role: 'close', label: '关闭窗口' } : { role: 'quit', label: '退出' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { role: 'resetZoom', label: '实际大小' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '缩小' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏切换' },
        { role: 'toggleDevTools', label: '开发者工具' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: '关于',
              message: '云手机群控客户端',
              detail:
                `版本：${app.getVersion()}\n` +
                'X86 云手机平台 PC 端（Electron 封装 Web 管理端）。\n' +
                'Web / PC / App 三端复用同一后端 API，数据一致。',
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ---- preload 桥的主进程侧实现 ----
ipcMain.handle('app:get-version', () => app.getVersion());
ipcMain.handle('app:get-platform', () => process.platform);
ipcMain.handle('shell:open-external', (_event, url) => {
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    return shell.openExternal(url);
  }
  return Promise.reject(new Error('仅允许打开 http/https 链接'));
});

// 单实例锁：群控客户端只允许开一个实例
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(() => {
    buildMenu();
    createMainWindow();

    app.on('activate', () => {
      // macOS：点击 Dock 图标时若无窗口则重建
      if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
    });
  });
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
