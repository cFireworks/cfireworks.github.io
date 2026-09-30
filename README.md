# cFireworks 技术博客

> 深入浅出，探究前沿技术

这是一个专注于 AI Agent、LLM、RAG、MCP、Skills Protocol 等前沿技术的中文技术博客。

**博客地址**：https://cfireworks.github.io

**默认分支**：`main`（2026-09-30 迁移）

## 特色

- 🔥 **热点技术**：紧跟 AI Agent 和 LLM 领域最新发展
- 💡 **独立见解**：不做简单转述，提供深度分析和实践经验
- 📊 **图文并茂**：丰富的架构图、对比表格和代码示例
- 🛠️ **可实践**：每篇文章都包含可落地的技术方案

## 技术栈

本博客使用 [Hexo](https://hexo.io/) 静态博客框架 + [NexT](https://theme-next.js.org/) 主题构建。

- **构建工具**：Hexo 8.x
- **主题**：hexo-theme-next
- **部署**：GitHub Actions 自动部署到 GitHub Pages

## 本地开发

### 环境要求

- Node.js 18+ 
- npm 或 yarn

### 安装依赖

```bash
npm install
```

### 本地预览

```bash
# 启动本地服务器
npx hexo server

# 浏览器访问
open http://localhost:4000
```

### 清理缓存

```bash
npx hexo clean
```

## 发布新文章

### 方式一：手动创建（推荐）

1. 在 `source/_posts/` 目录创建新的 Markdown 文件
2. 添加 Front Matter：

```markdown
---
title: 文章标题
date: 2026-09-30 18:00:00
categories:
  - AI Agent
tags:
  - 标签1
  - 标签2
---

文章内容...
```

3. 本地预览确认格式
4. 提交并推送到仓库

### 方式二：使用 Hexo 命令

```bash
npx hexo new post "文章标题"
```

会自动在 `source/_posts/` 创建文件。

### 文章规范

详细的写作规范和风格指南请参考 [EDITORIAL.md](./EDITORIAL.md)。

关键要点：
- 使用简体中文
- 包含代码示例和示意图
- 结构清晰，有独立见解
- 技术深度与可读性并重

## 自动部署

本仓库使用 GitHub Actions 自动部署到 GitHub Pages。

### 首次配置（重要）

**必须在仓库设置中启用 GitHub Actions 部署：**

1. 访问仓库 Settings → Pages
2. 在 **Source** 下拉菜单中选择 **GitHub Actions**（而不是 "Deploy from a branch"）
3. 保存设置

> ⚠️ **用户站点（如 cfireworks.github.io）必须使用 GitHub Actions 部署方式**，才能让源码保留在 master 分支，同时自动部署构建产物。

### 部署流程

1. 提交代码到 `master` 分支
2. GitHub Actions 自动构建 Hexo 静态文件
3. 自动部署到 GitHub Pages
4. 网站自动更新

**部署时间**：推送后约 2-5 分钟可在网站看到更新

### 手动触发部署

除了推送代码外，也可以在 Actions 页面手动触发部署：

1. 访问 [Actions](https://github.com/cFireworks/cfireworks.github.io/actions)
2. 选择 "部署博客到 GitHub Pages" 工作流
3. 点击 "Run workflow"

## 目录结构

```
.
├── .github/
│   └── workflows/
│       └── deploy.yml          # GitHub Actions 配置
├── source/
│   ├── _posts/                 # 博客文章 Markdown 源文件
│   └── images/                 # 图片资源
├── themes/                     # Hexo 主题
├── old-site/                   # 旧版静态网站备份（仅供参考）
├── _config.yml                 # Hexo 站点配置
├── package.json                # Node.js 依赖
├── EDITORIAL.md                # 编辑指南
└── README.md                   # 本文件
```

## 主题定制

如需定制主题样式，可以：

1. 在 `source/_data/` 目录创建主题配置覆盖文件
2. 或直接修改主题配置（参考 NexT 文档）

NexT 主题文档：https://theme-next.js.org/

## 常见问题

### 如何添加图片？

将图片放在 `source/images/` 目录，文章中引用：

```markdown
![图片描述](/images/your-image.png)
```

建议按月份组织图片：`source/images/2026-09/`

### 如何使用 Mermaid 图表？

Hexo 默认支持 Mermaid，直接在文章中使用：

\```mermaid
graph TD
    A[开始] --> B[结束]
\```

### 部署失败怎么办？

1. 检查 GitHub Actions 日志：仓库 → Actions 标签
2. 确认 `_config.yml` 配置正确
3. 确认依赖安装成功：`npm install`
4. 本地测试构建：`npx hexo generate`

### 如何修改站点配置？

编辑 `_config.yml` 文件，常用配置项：

```yaml
title: 站点标题
subtitle: 副标题
description: 站点描述
author: 作者名
language: zh-CN
timezone: Asia/Shanghai
url: https://cfireworks.github.io
```

## 贡献

欢迎提交 Issue 和 Pull Request！

如果你有好的技术文章想要投稿，请：
1. Fork 本仓库
2. 在 `source/_posts/` 创建文章
3. 提交 Pull Request

## 许可

博客内容采用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) 许可协议。

代码部分采用 MIT 许可。

---

**关注领域**：AI Agent · LLM · RAG · MCP · Skills Protocol · 开发者工具

**博客定位**：深入浅出，有独立见解的技术探究与实践

**更新频率**：持续更新中
