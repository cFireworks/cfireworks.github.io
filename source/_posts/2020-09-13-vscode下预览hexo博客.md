---
title: vscode下预览hexo博客
date: 2020-09-13 12:00:00
updated: 2020-09-26 12:00:00
categories:
  - Crabs
tags:
  - tech
  - web
  - hexo
---

在使用VS Code编辑hexo博客的过程中，使用markdown预览会出现问题，vscode自带的markdown渲染的效果与网页上显示的不一致，查阅了一些文章，找到一个合适的插件——`markdown-preview-enchanced`

总的来说，这个插件能够实现以下功能：

- 实时预览，可以自动生成目录链接辅助查看
- 支持主要的markdown语法，文章结构和hexo生成的基本一致
- 支持mathjax
- 支持pandoc渲染，可以将hexo换成pandoc进行render，使得线上与线下预览效果一致

## 一、插件配置

### 1.1 插件安装

`markdown-preview-enhanced`插件安装：

vs code的extension marketplace中搜索markdown-preview-enhanced，安装插件，并进入设置进行插件配置。

`Pandoc`安装：

```shell
suo apt-get install pandoc
```

### 1.2 配置修改

1. 搜索`Automatically Show Preview Of Markdown Being Edited`，勾选该选项设置自动预览。
2. 搜索`Math Rendering Option`,将选项更改为`MathJax`。
3. 搜索`Use Pandoc Parser`,勾选该选项使用`Pandoc`进行渲染。

## 二、代码块写法

之前使用的都是`code_block`的写法来标识代码块，这个并不能在普通的markdown预览中显示，通常都是使用一对三连反引号来标识代码块，看了些文章发现代码块还有多种写法，在这儿记录一下。

### 2.1 正常写法

```plain
``` [language]
code snippet
```
```

### 2.2 进阶写法

```plain
``` [language] [title] [url] [link text]
code snippet
```
```

> 参数含义如下：
> - language: 代码语言名称
> - title: 代码块标题，显示在左上角
> - url: 链接地址
> - link text: 链接名称，制定url后有效

### 示例

```plain
``` java /root/Demo.java
public class Demo{

}
```
```

效果如下：

```java
public class Demo{

}
```