# -*- coding: utf-8 -*-
"""把 usage_server.py + dashboard.html 打成单文件 exe。

用法（必须先装好 PyInstaller：pip install pyinstaller）：
    python packaging/build_exe.py

产物：
    ../dist/wb-usage.exe          单文件，拷走即用
    _build/ , wb-usage.spec       PyInstaller 中间产物，可随时删

设计要点：
    * dashboard.html 用 --add-data 打进 exe 作**兜底**；程序目录下若另有一个
      dashboard.html，那个优先（保留热加载，改前端不必重新打包）。
    * 只打包运行态需要的两个文件，不把日志、缓存、验证脚本卷进去。
    * 剔除 tkinter/unittest 等用不到的重模块压体积。
"""
import os
import subprocess
import sys
import time

# 英文版 Windows 的控制台代码页是 cp1252，直接 print 中文会 UnicodeEncodeError 崩掉
# （GitHub Actions 的 windows runner 就是这种情况）。统一切到 UTF-8，编不出来就替换。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.dirname(HERE)
ENTRY = os.path.join(SRV, 'usage_server.py')
HTML = os.path.join(SRV, 'dashboard.html')
DIST = os.path.join(SRV, 'dist')
BUILD = os.path.join(HERE, '_build')
NAME = 'wb-usage'

EXCLUDES = [
    'tkinter', 'unittest', 'pydoc', 'doctest', 'lib2to3',
    'test', 'distutils', 'setuptools', 'pip', 'pkg_resources',
]
# 注意：不要排除 email / html —— http.server 内部要用它们（格式化 Date 头、转义错误页）。
# 也不要排除 xml、urllib 子模块，收益小、踩坑概率高。


def main():
    for f, label in ((ENTRY, '入口脚本'), (HTML, '前端')):
        if not os.path.exists(f):
            print('缺少%s：%s' % (label, f))
            return 2

    args = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--console',
        '--name', NAME,
        '--distpath', DIST,
        '--workpath', BUILD,
        '--specpath', HERE,
        '--noconfirm',
        '--clean',
        # Windows 上 os.pathsep 是 ';'，POSIX 是 ':' —— 交给 os.pathsep 自适应
        '--add-data', HTML + os.pathsep + '.',
    ]
    for mod in EXCLUDES:
        args += ['--exclude-module', mod]
    args.append(ENTRY)

    print('即将执行：')
    print('  ' + ' '.join('"%s"' % a if ' ' in a else a for a in args))
    print()
    t0 = time.time()
    r = subprocess.run(args, cwd=HERE)
    dt = time.time() - t0
    print()
    print('PyInstaller 退出码 %d，耗时 %.1f 秒' % (r.returncode, dt))
    if r.returncode != 0:
        return r.returncode

    exe = os.path.join(DIST, NAME + '.exe')
    if not os.path.exists(exe):
        exe = os.path.join(DIST, NAME)          # 非 Windows
    if os.path.exists(exe):
        print('产物：%s  (%.1f MB)' % (exe, os.path.getsize(exe) / 1048576.0))
    else:
        print('未找到产物，请检查 dist 目录：%s' % DIST)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
