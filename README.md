# 跳过片头插件

Kodi 的 Skip Intro Addon 可通过多种检测方法和智能数据库系统智能检测、记忆和跳过电视节目的开场白。

## 特点

- **智能显示检测**

  - 自动识别电视节目和剧集
  - 支持 Kodi 元数据和文件名解析
  - 支持常见的命名格式（SxxExx、xxXxx）

- **简介/外展管理**

- 保存每一集的开场白/片尾曲时间
  - 重复使用保存的时间，以便将来播放
  - 多种检测方法：
    - 保存时间数据库
    - 章节标记
    - 可配置的默认时间
    - 支持在线应用程序接口（即将推出）

- **用户友好界面**

　- 右下方的跳过按钮干净利落、重点突出
  - 自动聚焦，可立即跳过
  - 可与遥控器、键盘和鼠标配合使用
  - 平滑的淡入/淡出动画
  - 非侵入式设计

- **技术特点**
  - 使用本地 Kodi 事件高效追踪时间
  - 用于高效存储的 SQLite 数据库
  - 智能持续时间解析（HH:MM:SS、MM:SS）
  - 全面的错误处理
  - 详细日志记录
  - 完全本地化支持

## 安装

1. **下载插件：**

   - 前往 [Releases](https://github.com/amgadabdelhafez/plugin.video.skipintro/releases) 部分
   - 下载最新版本的 zip 文件

2. **在 Kodi 中安装：**

   - 打开 Kodi > 插件
   - 点击 “软件包”图标（左上角）
   - 选择 “从压缩文件安装”
   - 导航至下载的压缩文件
   - 等待安装确认

3. **启用插件：**
   - 转到设置 > 附加组件
   - 在视频插件下找到“跳过介绍”
   - 启用插件

## Configuration

The addon provides three categories of settings:

1. **Intro Skipping Settings**

   - **Delay Before Prompt** (0-300 seconds)
     - How long to wait before showing the skip prompt
     - Default: 30 seconds
   - **Skip Duration** (10-300 seconds)
     - How far forward to skip when using default skip
     - Default: 60 seconds

2. **Database Settings**

   - **Database Location**
     - Where to store the show database
     - Default: special://userdata/addon_data/plugin.video.skipintro/shows.db
   - **Use Chapter Markers**
     - Enable/disable chapter-based detection
     - Default: Enabled
   - **Use Online API**
     - Enable/disable online time source (coming soon)
     - Default: Disabled
   - **Save Times**
     - Whether to save detected times for future use
     - Default: Enabled

3. **Show Settings**
   - **Use Show Defaults**
     - Use the same intro/outro times for all episodes
     - Default: Enabled
   - **Use Chapter Numbers**
     - Use chapter numbers instead of timestamps
     - Default: Disabled
   - **Default Intro Duration**
     - Duration of intro when using show defaults
     - Default: 60 seconds

## How It Works

The addon uses multiple methods to detect and skip intros:

1. **Database Lookup:**

   - Identifies current show and episode
   - Checks database for saved times
   - Uses saved times if available

2. **Chapter Detection:**

   - Looks for chapters named "Intro End"
   - When found, offers to skip to that point
   - Can save times for future use

3. **Manual Input:**

   There are two ways to access the time input feature:

   1. Through Skip Intro Button:

      - When the skip button appears, press menu/info
      - Choose chapters or enter manual times
      - Times are saved for future playback

   2. Through Library Context Menu:
      - In Kodi's TV show library, select a show or episode
      - Press 'C' or right-click to open context menu
      - Select "Set Show Times"
      - If the file has chapters:
        - Select chapters for intro start/end
        - Select chapter for outro start (optional)
        - Times are saved automatically
      * If no chapters available:
        - Enter intro start time and duration
        - Enter outro start time (optional)
        - Choose whether to use for all episodes

   When setting times, if chapters are available:

   - You'll be prompted to select chapters for:
     - Intro Start: Where the intro begins
     - Intro End: Where the intro finishes
     - Outro Start: Where the end credits begin
   - Chapter names and timestamps are shown
   - Selecting chapters automatically sets the times

   If no chapters are available, or if you prefer manual input:

   - Enter times in MM:SS format for:
     - Intro Start Time
     - Intro Duration
     - Outro Start Time (optional)
   - Choose whether to use these times for all episodes

   All times are saved in the database and used for future playback of the show.

4. **Default Skip:**

   - Falls back to configured delay if no other times found
   - Shows skip button after delay time
   - Option to save user-confirmed times

5. **Online API** (Coming Soon):
   - Will fetch intro/outro times from online database
   - Requires API key (not yet implemented)

## Repository Setup

To enable automatic updates:

1. **Add Repository:**

   - In Kodi > Add-ons > Package icon
   - Select "Install from zip file"
   - Navigate to `repository.plugin.video.skipintro.zip`
   - Wait for installation

2. **Updates:**
   - Kodi will automatically check for updates
   - Install updates through Kodi's addon manager

## Development

### Requirements

- Python 3.x
- Kodi 19 (Matrix) or newer

### Testing

The addon includes comprehensive unit tests:

```bash
python3 test_video_metadata.py -v
```

### Building

Use the included build script:

```bash
./build.sh
```

This will:

- Create addon zip file
- Generate repository files
- Update version information

### Project Structure

```
plugin.video.skipintro/
├── addon.xml           # Addon metadata and dependencies
├── default.py         # Main addon code
├── resources/
│   ├── lib/
│   │   ├── database.py   # Database operations
│   │   └── metadata.py   # Show detection
│   ├── settings.xml   # Settings definition
│   └── language/      # Localization files
├── tests/             # Unit tests
└── build.sh          # Build script
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add/update tests
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Changelog

### v1.3.8 (2025-02-19)

- Fixed settings parsing errors
- Improved database migration process
- Resolved issues with chapter-based skip time selection

### v1.3.7 (2025-02-19)

- Improved chapter-based skip time selection
- Enhanced database support for chapter-based configurations
- Fixed issues with saving and retrieving chapter-based settings

### v1.3.6 (2025-02-19)

- Fixed chapter-based skip time selection
- Improved reliability by using direct chapter number input

### v1.3.5 (2025-02-19)

- Recovered feature to set skip times based on chapters
- Added option to choose between manual time input and chapter-based selection
- Updated UI for improved user experience

### v1.3.4 (2025-02-19)

- Initial attempt at fixing database schema issues

### v1.3.3

- Fixed issue with setting manual skip times
- Improved database structure for new show entries
- Enhanced error handling and logging for better diagnostics
- Added verification of saved configurations
- Updated documentation

### v1.3.2

- Improved skip button UI and positioning
- Added smooth fade animations
- Switched to native Kodi event system
- Better performance and reliability
- Improved logging for troubleshooting
- Fixed timing issues during playback

### v1.3.0

- Added show-level default times
- Added duration-based skipping
- Added chapter number support
- Improved database persistence
- Better chapter name handling
- Fixed timing issues during playback
- Updated documentation

### v1.2.93

- Added HH:MM:SS duration parsing
- Improved settings with sliders and validation
- Added comprehensive error handling
- Added localization support
- Improved memory management
- Added unit tests

## Troubleshooting

If you encounter any issues with setting manual skip times:

1. Try setting manual skip times for a show again.
2. If problems persist, check the Kodi log file for detailed information about the process. Look for log entries starting with "SkipIntro:".
3. If you still experience issues, please report them on our GitHub issues page, including the relevant log entries for further investigation.
