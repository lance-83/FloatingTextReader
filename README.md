# FloatingTextReader 悬浮提词器

一个 Windows 桌面悬浮提词器：把小说 TXT 显示在无边框、置顶、半透明的悬浮窗里，
鼠标滚轮翻页，F1 老板键一键隐藏，阅读进度自动记到文件里，下次打开接着读。

> 说明：本仓库的源码最早是从打包好的 exe 反编译还原出来的（原作者即本人，源码曾丢失）。
> 还原后的代码与原程序在字节码层面逐条一致，之后在此基础上继续维护。

## 功能

- 导入 TXT 小说，自动尝试 UTF-8 / GBK / UTF-16 编码
- 无边框、置顶、背景半透明、按住左键可拖动
- 全局鼠标滚轮翻页，窗口不需要获得焦点
- 右键菜单调节：字体大小、每行字数、显示行数、文字颜色、窗口透明度、显示模式、滚动模式
- 老板键 F1，两种显示模式：
  - `F1 切换显示 / 隐藏`（默认）
  - `按住 F1 显示，松开消失`（显示时不抢焦点）
- 两种滚动模式：
  - `手动滚动`（默认）：滚轮翻页，可切单字 / 整行步进
  - `自动滚动`：定时自动前进，滚轮调速（0.6 ~ 6.0 行/秒，每档 0.2），`←` `→` 调节滚动方向
- 阅读进度自动写入小说文件末尾的 `#FTX#<id>#<offset>#` 标记行（只保留最近 3 条），
  下次导入同一个文件时自动跳回上次位置；标记行在显示时会被自动剥离
- ESC 退出；共享内存单实例保护

## 使用

1. 运行 `FloatingTextReader.exe`（或 `python main.py`）
2. 在悬浮窗上点右键 → `📂 导入TXT小说`
3. 滚轮翻页；F1 隐藏 / 显示；ESC 退出
4. 建议以管理员身份运行，否则全局滚轮钩子可能失效（启动时会有提示）

## 快捷键

| 操作 | 说明 |
| --- | --- |
| 鼠标滚轮 | 手动模式：翻页；自动模式：调节滚动速度 |
| F1 | 老板键（切换显示 / 按住显示，取决于菜单里选的显示模式） |
| ← / → | 自动滚动模式下调节滚动方向 |
| ESC | 退出程序 |
| 鼠标左键拖动 | 移动悬浮窗 |
| 鼠标右键 | 打开设置菜单 |

## 从源码运行

```bat
pip install -r requirements.txt
python main.py
```

需要 Python 3.8 以上（开发与打包用的是 3.12）。

## 打包成 exe

直接双击 `build.bat`，或在命令行执行：

```bat
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name FloatingTextReader --icon icon.ico main.py
```

产物在 `dist\FloatingTextReader.exe`。`--windowed` 表示不带控制台窗口
（程序内的提示信息用 `print` 输出，不带控制台时看不到，属于正常现象）。

## 可调参数

| 想改什么 | 位置 |
| --- | --- |
| 自动滚动速度范围与档位 | `main.py` 顶部 `AUTO_SPEED_MIN / MAX / STEP / DEFAULT` |
| 老板键换成别的键 | `main.py` 顶部 `VK_F1`（F2 = 113 …） |
| 默认字号 / 颜色 / 透明度 | `FloatingTextWindow.__init__` |
| 右键菜单里的可选字号列表 | `FloatingTextWindow.show_context_menu` |
| 进度标记格式 | `MARKER_PREFIX` / `MARKER_RE` / `build_marker` |

## 注意

阅读进度是直接写回小说文件末尾的，重要文件请自行备份。
