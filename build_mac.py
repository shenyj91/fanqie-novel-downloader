# -*- coding: utf-8 -*-
"""
打包脚本：macOS .app 版（番茄短篇下载器）
在 macOS 上运行：python build_mac.py
产出：dist/番茄短篇下载器.app
"""
import os
import shutil
import sys

def main():
    for d in ("build", "dist"):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    ascii_name = "FanqieShortDownloader"
    opts = [
        "--onefile",
        "--windowed",
        "--name", ascii_name,
        "--clean",
        "--noconfirm",
        "--osx-bundle-identifier", "com.syj.fanqie-short",
    ]
    if os.path.exists("icon.icns"):
        opts += ["--icon", "icon.icns"]
    opts.append("gui_short.py")

    import PyInstaller.__main__
    PyInstaller.__main__.run(opts)

    src = os.path.join("dist", ascii_name + ".app")
    dst = os.path.join("dist", "番茄短篇下载器.app")
    if os.path.exists(src):
        if os.path.exists(dst):
            shutil.rmtree(dst, ignore_errors=True)
        os.rename(src, dst)
        print("完成！app 位于 dist/番茄短篇下载器.app")
    else:
        print("警告：未找到产物，请检查 dist 目录")
        print("dist 内容:", os.listdir("dist") if os.path.isdir("dist") else "dist 不存在")


if __name__ == "__main__":
    sys.exit(main())
