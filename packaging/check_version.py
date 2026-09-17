# -*- coding: utf-8 -*-
"""校验 git 标签与前后端版本号是否对得上。

本项目前后端各自计版本：

    * 前端版本 = dashboard.html 里的 FE_VER
    * 后端版本 = usage_server.py 里的 BE_VER

之所以不用「标签决定版本」：前端是一个可以单独热替换的独立文件，后端是常驻服务，
两者各自演进。只改前端就只升 FE_VER，只改后端就只升 BE_VER。

代价是一个标签不可能同时等于两者（除非两边都升），所以判定标准放宽为
「标签至少等于其中一个」—— 只要对得上说明本次发布确实升了版本，
一个都对不上才说明「打了标签却忘了改版本号」。

用法：
    python packaging/check_version.py v1.0.1
    python packaging/check_version.py             # 不传则读环境变量 GITHUB_REF_NAME

退出码：
    0  一致，或无法判定（读不到版本号 / 没有标签）
    1  不一致（仅在 --strict 下；CI 默认只警告，不拦发布）
"""
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.dirname(HERE)

# BE_VER 的完整形态是：
#     BE_VER = os.environ.get('WB_VERSION', '').strip() or 'v1.0.1'
# 但也要容忍有人把它简化成直接赋字面量，所以两个模式依次尝试。
BE_PATTERNS = [
    re.compile(r"BE_VER[^\n]*?\bor\s+'([^']+)'"),
    re.compile(r"BE_VER\s*=\s*'([^']+)'"),
]
FE_PATTERNS = [
    re.compile(r"FE_VER\s*=\s*'([^']+)'"),
]


def _grab(path, patterns):
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except OSError as e:
        return None, '读不到 %s（%s）' % (path, e)
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(1), None
    return None, '在 %s 里没找到版本号常量' % os.path.basename(path)


def main():
    argv = [a for a in sys.argv[1:]]
    strict = '--strict' in argv
    argv = [a for a in argv if not a.startswith('--')]
    tag = argv[0] if argv else os.environ.get('GITHUB_REF_NAME', '')

    fe, fe_err = _grab(os.path.join(SRV, 'dashboard.html'), FE_PATTERNS)
    be, be_err = _grab(os.path.join(SRV, 'usage_server.py'), BE_PATTERNS)

    print('标签        : %s' % (tag or '(无)'))
    print('前端 FE_VER : %s' % (fe or '(%s)' % fe_err))
    print('后端 BE_VER : %s' % (be or '(%s)' % be_err))

    if fe_err or be_err:
        print('版本号解析不完整，跳过一致性判定。')
        return 0
    if not tag:
        print('没有标签（手动触发构建），跳过一致性判定。')
        return 0
    if not tag.startswith('v'):
        print('标签不以 v 开头，跳过一致性判定。')
        return 0

    if tag == fe == be:
        print('OK：标签与前后端版本号三者一致。')
        return 0
    if tag in (fe, be):
        which = '前端' if tag == fe else '后端'
        print('OK：标签与%s版本号一致（本次只动了%s）。' % (which, which))
        return 0

    msg = ('标签 %s 既不等于前端 %s 也不等于后端 %s —— '
           '多半是打了标签却忘了升版本号。' % (tag, fe, be))
    print('::warning title=版本号与标签不一致::%s' % msg)
    print('WARN：%s' % msg)
    return 1 if strict else 0


if __name__ == '__main__':
    sys.exit(main())
