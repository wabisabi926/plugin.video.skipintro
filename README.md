# Skip Intro - Kodi 剧集片头片尾自动跳过插件

<div align="center">

[![Version](https://img.shields.io/badge/version-1.3.7-blue.svg)](https://github.com/wabisabi926/plugin.video.skipintro)
[![License](https://img.shields.io/badge/license-NC--3.0-green.svg)](LICENSE.txt)
[![Platform](https://img.shields.io/badge/platform-Kodi-orange.svg)](https://kodi.tv/)

</div>

---

## 功能特性

- ✅ **自动跳过片头片尾**：首次记录后，自动跳过片头片尾
- ✅ **一季只记一次**：每季只需记录一次片头片尾时间点
- ✅ **智能自动播放**：片尾结束后 6 秒自动播放下一集
- ✅ **支持三种模式**：播放列表模式（最高优先级）→ 媒体库模式 → 文件夹播放模式
- ✅ **智能自动播放检查**：首次使用时自动检测并提示开启 Kodi 自动播放设置
- ✅ **数据持久化**：记录数据保存在本地，重启不丢失
- ✅ **安全写入**：原子写入 + 备份恢复机制
- ✅ **播放列表补全**：解决 OSD 播放列表偶发性排序错乱问题（默认关闭）

---

## 目录

1. [安装步骤](#1-安装步骤)
2. [基础配置](#2-基础配置)
3. [按键映射](#3-按键映射)
4. [使用教程](#4-使用教程)
5. [插件设置](#5-插件设置)
6. [常见问题](#6-常见问题)
7. [手动配置](#7-手动配置)
8. [接口说明](#8-接口说明)

---

## 1. 安装步骤

### 方法一：从 ZIP 文件安装（推荐）

1. 下载最新版本的插件压缩包（`.zip` 文件）
2. 打开 Kodi → 设置 → 插件 → 从 Zip 文件安装
3. 选择下载的 `.zip` 文件
4. 安装完成后在「我的插件」→「程序插件」中找到插件

### 方法二：手动安装

1. 将插件文件夹复制到 Kodi 插件目录：
   ```
   Windows: %APPDATA%\Kodi\addons\
   Linux: ~/.kodi/addons/
   macOS: ~/Library/Application Support/Kodi/addons/
   Android: Android/data/org.xbmc.kodi/files/.kodi/addons/
   ```
2. 重启 Kodi 使插件生效

---

## 2. 基础配置

### 2.1 启用 Kodi 自动播放

**这是插件工作的前提条件！**

1. 打开 Kodi → 设置 → 播放器设置（切换到高级模式或专家模式）
2. 进入「播放」选项卡
3. 找到「自动播放下一个视频」
4. 配置播放列表行为：
   - ✅ **电视剧、剧集** - 必须勾选
   - ⬜ **电视频道** - 可选
   - ✅ **未分类** - 文件夹播放时必须勾选

### 2.2 安装按键映射插件（推荐）

为了更方便地使用快捷键，推荐安装「按键映射魔改版」插件：

1. 下载 [按键映射魔改版插件](https://github.com/wabisabi926/script.keymap)
2. 安装方法同上（从 ZIP 安装）
3. 安装后在 Kodi → 设置 → 插件 → 我的插件 → 程序插件 中找到并启用

---

## 3. 按键映射

### 3.1 使用按键映射魔改版（推荐）

1. 在 Kodi 中打开「按键映射魔改版」插件
2. 选择「编辑快捷键」
3. 找到以下功能并映射到遥控器按键：
   - **记录当前时间为记录点（片头/片尾）**
   - **删除当前剧集的记录点**
4. 💡 **小技巧**：将两个功能映射到同一个按键
   - 短按 = 记录
   - 长按 = 删除

### 3.2 手动编辑 Keymap

如果不使用按键映射插件，也可以手动配置：

1. 找到或创建 `keymaps` 文件：
   ```
   Windows: %APPDATA%\Kodi\userdata\keymaps\
   Linux: ~/.kodi/userdata/keymaps/
   ```

2. 新建或编辑 `gen.xml` 文件：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<keymap>
    <FullscreenVideo>
        <keyboard>
            <!-- 短按：记录片头/片尾时间点 -->
            <key id="12345">RunScript(plugin.video.skipintro, ?mode=record_skip_point)</key>
            <!-- 长按：删除记录 -->
            <key id="12345" mod="longpress">RunScript(plugin.video.skipintro, ?mode=delete_skip_point)</key>
        </keyboard>
        <remote>
            <!-- 如果使用遥控器，也可以在此配置 -->
        </remote>
    </FullscreenVideo>
</keymap>
```

3. 重启 Kodi 使配置生效

### 3.3 按键 ID 查询

常用按键 ID 参考：

| 按键 | ID | 说明 |
|------|-----|------|
| `*`（星号） | 61514 | 常用选择键 |
| `#`（井号） | 61513 | 常用返回键 |
| 上方向键 | 61448 | - |
| 下方向键 | 61450 | - |
| 左方向键 | 61451 | - |
| 右方向键 | 61452 | - |
| 确定/OK | 61453 | - |
| 返回/Back | 61448 | - |

---

## 4. 使用教程

### 4.1 首次使用 - 记录片头片尾

**Step 1：播放剧集**

在 Kodi 中打开一个电视剧剧集开始播放。

**Step 2：记录片头**

当片头开始播放时，按下映射好的按键（或短按）：
- 插件会记录当前时间点
- 屏幕显示「片头跳过时间已记录」
- 下次播放时自动跳过这段内容

**Step 3：记录片尾**

继续播放到片尾开始时，再次按下按键：
- 插件会记录片尾开始时间点
- 屏幕显示「片尾跳过时间已记录」
- 下次播放时自动跳过这段内容

### 4.2 后续使用 - 自动跳过

完成记录后，插件将自动工作：

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   [片头] ──跳过──▶ [正片开始] ──播放──▶ [片尾] ──跳过──▶  │
│                           │                    │            │
│                    首次播放记录      自动跳过 + 6 秒后播放下一集  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**自动播放说明**：
- 片尾结束后会显示 6 秒倒计时
- 倒计时结束自动播放下一集
- 倒计时期间可按“返回键”取消自动播放下一集

### 4.3 一季只记一次

**重要特性**：剧集每季只需记录一次！

- 记录的时间点会自动应用到该季的所有剧集
- 例如：记录了「S01」的片头片尾，所有第 1 季的剧集都会自动跳过
- 不同季度需要分别记录

### 4.4 删除/修改记录

如果需要修改跳过时间：

1. 播放到片头/片尾位置
2. 长按映射好的按键（或执行删除功能）
3. 插件会删除当前季度的跳过记录
4. 重新记录新的时间点

---

## 5. 插件设置

在 Kodi 中访问：设置 → 插件 → 我的插件 → 程序插件 → Skip Intro → 设置

### 5.1 播放列表设置

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| **自动补全播放列表** | 播放时自动补全当前季的播放列表 | 关闭 |

### 5.2 调试设置

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| **调试模式** | 启用后将输出详细日志 | 关闭 |

---

## 6. 常见问题

### Q1：插件安装后没有反应？

**解决方案**：
1. 确认已在 Kodi 中启用插件
2. 检查 Kodi 播放器设置中的「自动播放下一个视频」是否已勾选电视剧/剧集/未分类
3. 检查是否已正确配置按键映射
4. 开启插件的「调试模式」，查看 Kodi 日志

### Q2：自动播放下一集不生效？

**检查清单**：
1. ✅ Kodi 设置 → 播放器 → 自动播放下一个视频 →「电视剧、剧集」已勾选
2. ✅ 如果是文件夹播放，已勾选「未分类」

### Q3：片头片尾没有正确跳过？

**可能原因**：
1. 时间点记录位置不正确（片头应在 0-20% 位置，片尾应在 80-100% 位置）
2. 当前季度没有记录，需要重新记录
3. 剧集信息不完整（如缺少季数信息）

### Q4：如何查看 Kodi 日志？

**Windows**：
```
%APPDATA%\Kodi\kodi.log
```

**Linux/macOS**：
```
~/.kodi/temp/kodi.log
```

**Android**：
```
Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log
```

### Q5：记录数据保存在哪里？

插件数据保存在 Kodi 用户数据目录：
```
addon_data/plugin.video.skipintro/skip_intro_data.json
```

### Q6：如何重置所有记录？

删除数据文件即可：
1. 关闭 Kodi
2. 删除 `%APPDATA%\Kodi\userdata\addon_data\plugin.video.skipintro\skip_intro_data.json`
3. 重启 Kodi

---

## 7. 手动配置

### 7.1 直接调用插件接口

可以通过 Kodi 的「运行脚本」功能直接调用：

**记录跳过点**：
```
RunScript(plugin.video.skipintro, ?mode=record_skip_point)
```

**删除跳过点**：
```
RunScript(plugin.video.skipintro, ?mode=delete_skip_point)
```

### 7.2 自定义快捷键

在 `keymaps/gen.xml` 中添加更多快捷键：

```xml
<keymap>
    <Global>
        <keyboard>
            <!-- 全局快捷键：任意界面都可使用 -->
            <key id="xxx">RunScript(plugin.video.skipintro, ?mode=record_skip_point)</key>
        </keyboard>
    </Global>
    <FullscreenVideo>
        <keyboard>
            <!-- 仅在视频全屏播放时生效 -->
            <key id="xxx">RunScript(plugin.video.skipintro, ?mode=record_skip_point)</key>
        </keyboard>
    </FullscreenVideo>
</keymap>
```

---

## 8. 接口说明

### record_skip_point（记录跳过点）

**功能**：将当前播放时间记录为片头或片尾跳过点

**判断规则**：
- 播放进度在 0-20%：记录为片头结束时间
- 播放进度在 80-100%：记录为片尾开始时间
- 其他位置：不做任何操作

**返回值**：显示通知提示记录结果

### delete_skip_point（删除跳过记录）

**功能**：删除当前季度所有跳过记录

**判断规则**：
- 播放进度在 0-20%：删除片头记录
- 播放进度在 80-100%：删除片尾记录
- 其他位置：不做任何操作

**返回值**：显示通知提示删除结果

---

## 更新日志

### v1.3.7 (2026-05)
- ✅ **日志时间戳**：每条日志添加 `YYYY-MM-DD HH:MM:SS` 时间戳，便于问题追踪
- ✅ **常量集中化**：将魔法数字集中定义为常量（播放停止超时、通知持续时间等）
- ✅ **代码精简**：`State` 类使用 Python 属性替代显式 getter/setter 方法
- ✅ **错误处理增强**：新增 `log_error`, `log_warning`, `log_debug` 函数和 `catch_exceptions` 装饰器
- ✅ **播放时间获取优化**：添加视频播放检查和时间值验证，防止无效数据

### v1.3.6 (2026-05)
- ✅ 设置界面重构，分为「常规」和「日志」两个类别
- ✅ 新增「删除所有记录点」功能，支持一键清除所有跳过时间点（带确认对话框）
- 🐛 修复取消跳过后后续剧集无法自动跳过的问题
- 📝 精简核心函数代码，移除冗余代码

### v1.3.5 (2026-05)
- ✅ 播放到最后一集时显示「已播放完最后一集」提示
- ✅ 最后一集不再显示误导性的「即将播放下一集」倒计时窗口
- ✅ 优化最后一集检测逻辑，支持三种播放模式
- 📝 修正翻译文字，让提示更自然

### v1.3.3 (2026-05)
- ✅ 代码结构优化，减少 19% 代码量
- ✅ 优化数据持久化，添加原子写入和备份恢复机制
- ✅ 优化设置管理，添加 SettingsManager 类
- 🐛 修复方法命名冲突问题

### v1.3.2
- ✅ 支持目录模式播放
- ✅ 提取通用季/集号获取函数
- 🐛 修复目录模式剧集号显示问题

### v1.3.1
- ✅ 优化片尾跳过逻辑
- ✅ 添加自动播放功能

### v1.3.0
- ✅ 首次发布

---

## 技术支持

- **问题反馈**：[GitHub Issues](https://github.com/wabisabi926/plugin.video.skipintro/issues)
- **功能建议**：[GitHub Discussions](https://github.com/wabisabi926/plugin.video.skipintro/discussions)
- **源码地址**：[GitHub Repository](https://github.com/wabisabi926/plugin.video.skipintro)

---

## 致谢

- [Kodi 官方文档](https://kodi.wiki/view/Main_Page)
- [Kodi Add-on Development Guide](https://kodi.wiki/view/Add-on_development)

---

<div align="center">

**仅供个人使用 | For Personal Use Only**

</div>
