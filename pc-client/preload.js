/**
 * preload：在 contextIsolation 开启的前提下，向 Web 管理端暴露一个最小桥接层。
 *
 * 渲染进程（Vue 前端）可通过 window.cloudPhoneDesktop 判断"是否运行在 PC 客户端内"，
 * 并获取版本号 / 平台信息、用系统浏览器打开外链。除此之外不暴露任何 Node 能力。
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cloudPhoneDesktop', {
  /** 标记：前端可据此显示"PC 客户端"徽标或隐藏浏览器专属提示 */
  isDesktop: true,

  /** 客户端版本号（取自 package.json version） */
  getVersion: () => ipcRenderer.invoke('app:get-version'),

  /** 运行平台：win32 / darwin / linux */
  getPlatform: () => ipcRenderer.invoke('app:get-platform'),

  /** 用系统默认浏览器打开外部链接（仅 http/https） */
  openExternal: (url) => ipcRenderer.invoke('shell:open-external', url),
});
