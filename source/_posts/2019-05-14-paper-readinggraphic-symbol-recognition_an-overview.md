---
title: Paper Reading:Graphic Symbol Recognition_an overview
date: 2019-05-14 12:00:00
updated: 2020-09-13 12:00:00
categories:
  - Paper
tags:
  - paper
  - graphic symbol recognition
---

# 论文《Graphic Symbol Recognition:An Overview》

## 摘要

> **Abstract：**Symbol recognition is one of the primary stages of any graphics recognition system. This paper reviews the current state of the art in graphic symbol recognition and raises some open issues that need further investigation. Work on symbol recognition tends to be highly application specific. Therefore, this review presents the symbol recognition methods in the context of specific applications.

本篇论文是1998年发表在GREC上的一篇综述文章，介绍了当时为止`符号检测`领域的研究情况，并提出了待研究的问题。

## 一、介绍

> In order to distinguish symbol recognition from character recognition, we use the term ‘**graphic symbol recognition**‘.

该论文将符号识别问题与字符识别问题进行区分，定义此类问题为图像符号识别。

> However, to provide a frame of reference for symbol recognition, we briefly discuss the various stages in a diagram/drawing recognition system.
> *The first phase*of any such system is the image preprocessing step.
> *The second stage*performs detection of graphical primitives such as lines, arcs, text regions, etc.
> *The syntactic phase*imposes a grammar on the recognized graphical symbols and primitives.

在图像识别系统中，通常分为三个步骤：

- 图像预处理步骤，包括噪声去除、二值化、细化处理等
- 图元的检测步骤，例如线、圆弧、文字区域的检测
- 语义理解部分，从符号和图元中解析出有意义的信息（分类等）

## 二、应用和方法

### 2.1 电路图

> Electrical circuits are typically composed of**symbols**,**interconnections**, and**annotations**.

电路图主要包含三个部分：`符号`、`连接`、`标注`

### 论文一： “An automatic circuit diagram reader with loop-structure-based symbol recognition”

> Okazaki et al. describe a logic diagram reader that recognizes loop structured symbols by symbol segmentation and identification.
> **Key words: loop structured symbols**

#### 1）简介

该论文提出了一种方法，用于对VLSI-CAD输入数据中的逻辑电路图进行识别，逻辑电路图大多具有环结构，本论文首先对环状符号进行识别，用以对候选环进行检测。本文处理的环状符号具有以下属性：

- 符号由一个或多个基本环图元构成（基本环图元是没有子环的环状符号）
- 符号的尺寸、方向和位置是不固定的
- 符号之间通过连接线连接，且分布非常密集
- 许多符号都比较相似
- 新图元需要被使用者添加

检测候选环之后，对环状符号进行识别，这是一个two-stage识别过程。第一步是符号分割（`symbol segmentation`），先对候选环的合理性进行确定并分割出相应区域。第二步是符号识别（`symbol identification`），对分割出的区域进行分析得出结论。符号分割和符号识别都由决策树进行控制。

#### 2）基于环结构的符号分割

独立环检测步骤，一个独立的环可以通过连通分量标签（`component labeling`）的方法找到。之后是分割出最小分析区域（minimum region for analysis,`MRA`），MRA中包含着识别符号的所有组成部分，但区域最小。可以说是从候选基本环状图元扩大到包含符号的所有组件，但又不至于更大到包含多个符号。
MRA的计算策略如下：

- 符号集合是预定义的，模板符号的尺寸固定，最多有8个实现，包括四个方向和镜像表示
- 除了无环符号，所有符号都具有某个特征环（`characteristic loop`），即不同符号的公共基本环图元
- 所有符号具有相应的符号窗口（`symbol window`），是适应符号大小的矩形窗口
- 定义特征环（`characteristic loop`）的中心为基点（`base point`）
- 定义特征窗口（`characteristic window`）为所有包含该特征环的不同符号的符号窗口的合并
- 有相同特征窗口的被归回中间类别（`intermediate categories`）

根据一个候选环获得MRA，包括三个步骤：
Step 1 ：通过候选环形图提取8个特征

- Feature1：环形面积
- Feature2-5：四类mask patterns出现的数目，近似于四种斜率直线的长度
- Feature6：三分支节点的数量（假设图像是细化图像）
- Feature7-8：适应候选环大小的矩形宽、高

Step 2 ：基于8个特征，使用决策树来确定候选环所属的中间类别以及方向
Step 3 ：根据上一步的中间类别结果和先验MRA信息确定MRA结果

#### 3）基于环结构的启发式混合符号识别

符号识别步骤，在MRA和中间类别已知的情况下计算得到符号的具体类型。一个简单的符号识别方法是模板匹配（`template matching`），步骤如下：

- 准备独立环状图作为图元模板（`primitive templates`），例如基本圆、三角、矩形。将图元模板分为两大类，一类是基类符号（`radical symbols`），另一类是辅助符号（`auxiliary symbols`）
- 执行模板匹配，使用一个多步匹配过程的决策树。

另一种模板匹配方法：
Step 1 ：从MRA中提取特征

- 连接线的数量
- X方向和Y方向上的尖峰数量
- 簇（`cluster`）数量及其集合特征
- several local features of the filled-hole image

以一定的规则合并两种方法识别的结果。

Step 2 ：根据以上特征从MRA中识别符号

#### 4）字符识别、无环符号和矩形识别、线的分析

---

### 论文二： “Recognizing hand-written electrical circuit symbols with attributed graph matching”

> Lee proposes a model based approach to electrical circuit symbol recognition. A hybrid representation of a symbol, called an attribute graph, incorporating structural and statistical features of the symbol, is used for symbol matching.
> **Key words: attribute graph, incorporating structural, statistical features**

#### 1）简介

该论文提出一种检测手写电路图符号的方法，使用一种混合表示：属性图（`attributed graph`,`AG`），结合结构和统计特征的图像模式（`image patterns`）

#### 2）属性图的构建

**属性图表示的定义**
属性图中的属性是由在单像素宽度线表示的符号中段或顶点图元（`segment primitive`,`vertex primitive`）构成的局部结构的数值特征。对于段图元（`segment primitive`）， 长度、曲率、两端点是属性；对于顶点图元（`vertex primitive`），位置、类型（终点、拐点、连接点）、连接该顶点的段列表、连接该顶点的段的角度列表是属性。
根据以上属性还可以得到统计属性，对于段图元，这些属性包括数量、平均长度、长度的方差、平均曲率、曲率方差；对于顶点图元，这些属性包括统计数量、平均坐标位置、平均坐标位置方差和连接段的直方图。
**构建一个属性图**
Step 1 ：快速细化（`Fast skeletonization`）
在校正阴影和阈值分割（*Low-level image processing by max-min filters*）后，使用快速细化算法（*A Contour Processing Method for Fast Binary Neighborhood Operations*）获取符号图形的骨架。
Step 2 ：线跟踪和分段近似（`Line-tracking`,`piecewise segment approximation`）：
在细化图中，不同类型的像素点包括终点、拐点和连接点像素。线跟踪用于找到不同的骨架部分。 该骨架部分被近似为直线或是圆弧通过以下策略确定：

1. The maximum distance is calculated between the part and the straight linesegment.
2. When this distance exceeds a threshold dc, a circular line-segment is calculated through the endpoints of the skeleton part and the pixel in the middle of the part.
3. The maximum distance between the circular line-segment and the skeleton
part is calculated.
4. When this maximum distance is smaller than the one of the straight line
approximation, the circular approximation is used.
5. When the maximum distance exceeds a threshold dmax , the skeleton part is split at the pixel of maximum distance to the straight line.
6. Above five steps are repeated on both resulting parts until the dmax condition is satisfied.

Step 3 ：错误纠正（`Error recovery`）：

1. Two close end points within a threshold $d_{min}$ from each other are joined.
2. All segments with at least one end point and shorter than a threshold $d_{min}$ are removed.
3. All other segments shorter than a threshold $d_{min}$ are absorbed.
4. End points within a distance $d_{min}$ from a straight or a circular line-segment are attached to it, resulting in a junction and the splitting of the straight or circular line-segment.
5. Two close segments within a threshold $d_{min}$ from each other are joined.
6. Corners between straight line-segments with an angle close to 1800 are deleted and the segments are joined.
7. Small loops are deleted.

### 论文三： “A symbol recognition system”

> Cheng et al. present a neural network based symbol recognition system for electrical drawings.
> **Key words: neural network**

### 论文四： “A new system for the analysis of schematic diagrams”

> Hamada proposes a schematic diagram interpretation system in which electrical symbol recognition and detection of connecting lines are interdependent.
> **Key words: connecting lines**

### 论文五： “Recognition of logic diagrams by identifying loops and rectilinear polylines”

> Kim et al. propose a system to recognize logic diagrams by identifying loops and rectilinear polylines. Preprocessing is done to convert an image into its line skeleton description. The symbol feature set includes Fourier descriptors for loops and six-tuple line segment based moment invariants for symbols.
> **Key words: loops, rectilinear polylines, line skeleton description**

## 三、Open Issues

> - Graphic symbol recognition seems to be trapped in a low level recognition mode. Very little work has been done on trying to correct the errors made by symbol segmenting and matching techniques using feedback from the syntactic or semantic stages of a drawing or diagram recognition system.
> - Most symbol recognition methods do not address the scalability issue. How is the cost of symbol representation, and the computational cost of recognition, affected by increase in the number of prototype symbols? Is there a limit to the number and the type of prototype symbols at which the system performance degrades seriously?
> - How do the symbol recognition methods degrade with noise? Are they robust in the presence of image noise and/or unreliable graphical primitive detection? How sensitive are the methods to the number of training samples per prototype symbol?
> - Is there a best symbol representation? The best representation should be compact, incrementally extensible, computationally inexpensive for generating symbol hypotheses, capable of representing all symbol types, capable 76 of representing similar symbol prototypes with a similar representation or a shared representation, and insensitive to noise.
> - Is there a best method for general symbol recognition? Is there a best method for a specific symbol recognition domain? No meaningful comparisons between various methods are available. One is hard pressed to find a publication on a symbol recognition method that compares its method with any other method in a systematic and quantitative way.
> - Is there a way for researchers to compare their methods with other methods?In other words, where is the practice, that is commonplace in successful pattern recognition domains, of reporting results on standard databases of training and test patterns?
> - Is is possible to evaluate and compare all or most symbol recognition methods in a domain independent manner?
> - There is a need for comprehensive performance measures and experimental protocols to enable a comparison of symbol recognition methods.