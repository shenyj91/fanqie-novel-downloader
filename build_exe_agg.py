# -*- coding: utf-8 -*-
"""
聚合版（番茄+七猫）exe 打包脚本
用法: python build_exe_agg.py
"""
import os
import shutil

def main() -> None:
    for d in ("build", "dist"):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    opts = ["--onefile", "--windowed", "--name", "fanqie_qimao_agg", "--clean", "--noconfirm"]
    if os.path.exists("icon.ico"):
        opts += ["--icon", "icon.ico"]
    opts.append("gui_agg.py")

    import PyInstaller.__main__
    PyInstaller.__main__.run(opts)

    src = os.path.join("dist", "fanqie_qimao_agg.exe")
    dst = os.path.join("dist", "\u756a\u8304\u4e03\u732b\u805a\u5408\u4e0b\u8f7d\u5668.exe")  # 番茄七猫聚合下载器.exe
    if os.path.exists(src):
        os.rename(src, dst)
    print("Done. exe at dist/")

if __name__ == "__main__":
    main()
