# Kodi 剧集跳过片头片尾插件

## 功能介绍
- 支持手动记录剧集的片头和片尾时间点(一季记录一次)。
- 自动跳过已记录的片头和片尾，实现无缝追剧体验。

## 使用办法
1. 前提：设置-播放器-自动播放下一个（勾选"电视剧，剧集"）
2. 安装按键映射魔改版 地址： [https://github.com/wabisabi926/script.keymap](https://github.com/wabisabi926/script.keymap)
3. 用按键映射魔改版映射"记录当前时间为跳过点 (片头/片尾)"和"删除当前剧集的跳过点记录"两个功能。建议用映射到同一个按键，短按为"记录"，长按为"删除"。

## 使用示例

### 1. 绑定到遥控器按键 (Keymap)
- 方法1：使用 按键映射魔改版 插件进行按键映射。
  
- 方法2：手动编辑 `userdata/keymaps/gen.xml` (或新建)，将功能绑定到想要映射的按键。
  
  示例：
```xml
<keymap>
  <FullscreenVideo>
    <keyboard>
      <!-- 想要映射的按键短按: 记录片头或片尾的时间点 -->
      <key id="61514">RunScript(plugin.video.skipintro, ?mode=record_skip_point)</key>
      <!-- 想要映射的按键长按: 删除片头或片尾的时间点 -->
      <key id="61514" mod="longpress">RunScript(plugin.video.skipintro, ?mode=delete_skip_point)</key>
    </keyboard>
</keymap>
```
    
## 接口列表

### 跳过片头片尾接口
**记录当前时间为跳过点 (片头/片尾)**
- 在剧集播放的前 20% 调用记录为片头结束点。
- 在剧集播放的后 20% 调用记录为片尾开始点。
```xml
RunScript(plugin.video.skipintro, ?mode=record_skip_point)
```

**删除当前剧集的跳过点记录**
```xml
RunScript(plugin.video.skipintro, ?mode=delete_skip_point)
```
