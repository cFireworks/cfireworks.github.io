---
title: Windows Terminal 预览
date: 2019-05-10 12:00:00
updated: 2020-09-13 12:00:00
categories:
  - Crabs
tags:
  - tech
  - utils
---

## 简介

微软在 Build 2019 宣布了新的命令行应用 Windows Terminal，支持 PowerShell、CMD、以及 Windows Subsystem for Linux（WSL）。

Windows Terminal 支持多 Tabs 体验、系统主题、插件、GPU 渲染加速，完整支持 Unicode（东亚语言、Emoji 等）。

目前Windows Terminal还没有提供正式版本，需要自己通过源码编译。

## 一、安装

### 1. 下载项目

首先，从GitHub上复制这个项目

```plain
git clone https://github.com/microsoft/Terminal.git
git submodule update --init --recursive
```

### 2. build and install

开发环境配置

- “Desktop Development with C++”
- “Universal Windows Platform Development”
- Windows 10 1903 SDK (10.0.18362.0)
- “v141 Toolset”

Build 步骤

1. Visual Studio打开`OpenConsole.sln`
2. 设置平台（`x86/x64`）和生成模式（`debug/release`），运行生成解决方案
3. 若出现报错error C2220，则将相关文件编码方式改为`UTF-8`；main.cpp中换行符问题，则在str常量前加上前缀`u8`
4. 系统设置中 - 更新 - 开发者选项 - App sources更改为开发者模式
5. 右击`Solution/Terminal/CascadiaPackage`，选择`部署`进行安装

### 3. 设置

在开始菜单可以找到`Windows Terminal(Preview)`，打开后还不能看到菜单按钮，摁下快捷键`Ctrl + T`新建一个子窗口，可以看到菜单栏，选择`Settings`可以修改`profiles.json`文件进行配置。

### 4. 添加 WSL

1. Create a new session in`profiles`, with content copied from`profiles/cmd`
2. Give it a new`guid`
3. Give it a new`name`, such as`WSL`
4. Specify its`commandline`to`wsl.exe`

下拉菜单可以看到`WSL`选项，示例如下：

```plain
{
    "guid": "{09dc5eef-6840-4050-ae69-21e55e6a2e62}",
    "name": "WSL",
    "colorscheme": "Campbell",
    "historySize": 9001,
    "snapOnInput": true,
    "cursorColor": "#FFFFFF",
    "cursorShape": "bar",
    "commandline": "wsl.exe",
    "fontFace": "Consolas",
    "fontSize": 12,
    "acrylicOpacity": 0.75,
    "useAcrylic": true,
    "closeOnExit": false,
    "padding": "0, 0, 0, 0"
}
```

## 二、体验

使用上的感受，Windows Terminal是一个可以搭载CMD、Power Shell、WSL的平台，外观更加好看，支持子窗口。目前子窗口无法拖动更改顺序，主题配置也没有界面操作，只能通过更改json文件来实现。关于Windows Terminal对字体、表情更好的支持，还没有测试使用。