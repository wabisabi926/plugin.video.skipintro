# Kodi 剧集跳过片头片尾插件（基于X佬的万能插件精简）

## 功能介绍
    * 支持手动记录剧集的片头和片尾时间点(一季记录一次)。
    * 自动跳过已记录的片头和片尾，实现无缝追剧体验。

## 使用示例

### 1. 绑定到遥控器按键 (Keymap)
    * 方法1：使用 按键映射魔改版 插件进行按键映射。（推荐）
      按键映射魔改版 
      地址： https://github.com/wabisabi926/script.keymap
      
    * 方法2：新建或编辑（如无） `userdata/keymaps/gen.xml` 文件，将插件功能绑定到想要映射的按键。
    
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

###  跳过片头片尾接口
**记录当前时间为跳过点 (片头/片尾)**
    *  在剧集播放的前 20% 调用记录为片头结束点。
    *  在剧集播放的后 20% 调用记录为片尾开始点。
```xml
RunScript(plugin.video.skipintro, ?mode=record_skip_point)
```

**删除当前剧集的跳过点记录**
```xml
RunScript(plugin.video.skipintro, ?mode=delete_skip_point)
```
