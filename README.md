# Kodi 剧集跳过片头片尾插件

## 功能介绍
    * 支持手动记录剧集的片头和片尾时间点(一季记录一次)。
    * 自动跳过已记录的片头和片尾，实现无缝追剧体验。

## 接口调用
    * 可以通过 `RunScript` 命令调用本插件提供的接口功能。  
    * 可以绑定到遥控按键

## 使用示例

### 1. 绑定到遥控器按键 (Keymap)
编辑 `userdata/keymaps/gen.xml` (或新建)，将功能绑定到特定按键。

**示例：绑定启动筛选页面 (v12红色键) 及跳过功能 (v12蓝色键)**
```xml
<keymap>
  <FullscreenVideo>
    <keyboard>
      <!-- 蓝色键短按: 记录片头或片尾的时间点 -->
      <key id="61514">RunScript(plugin.video.skipintro, ?mode=record_skip_point)</key>
      <!-- 蓝色键长按: 删除片头或片尾的时间点 -->
      <key id="61514" mod="longpress">RunScript(plugin.video.skipintro, ?mode=delete_skip_point)</key>
    </keyboard>
</keymap>
```

## 接口列表

###  跳过片头片尾接口
**记录当前时间为跳过点 (片头/片尾)**
*   在剧集播放的前20%调用记录为片头结束点。
*   在剧集播放的后20%调用记录为片尾开始点。
```xml
RunScript(plugin.video.skipintro, ?mode=record_skip_point)
```

**删除当前剧集的跳过点记录**
```xml
RunScript(plugin.video.skipintro, ?mode=delete_skip_point)
```
