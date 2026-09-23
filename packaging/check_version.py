# -*- coding: utf-8 -*-
"""校验发行标签的形态：必须是 vX.Y.Z，且 X / Y / Z 各只有一位数字（0-9）。

规则来源（2026-09-23 用户指定）：
    三套版本互相独立 —— 前端一个版本（dashboard.html 的 FE_VER）、后端一个版本
    （usage_server.py 的 BE_VER）、发行一个版本（git 标签 / Release）。
    发行版本每发行一次 +1，且**每位只占一位数字**：某一位到 9 就进位 ——
    所以 v1.0.9 的下一个是 v1.1.0（不是 v1.0.10），v1.9.9 的下一个是 v2.0.0。

因此本脚本**不再比较「标签是否等于前后端版本号」**：发行版本本来就独立于两者，
那种比较必然报警。FE_VER / BE_VER 仍会打印出来，但**仅供参考、不参与判定** ——
它们只是让发版日志里能同时看到三套版本，便于人工核对。

用法：
    python packaging/check_version.py v1.1.4
    python packaging/check_version.py             # 不传则读环境变量 GITHUB_REF_NAME

退出码：
    0  形态合法，或无法判定（没有标签 / 不是 v 开头的发行标签）
    1  形态不合法（仅在 --strict 下；CI 默认只警告，不拦发布）
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

# 合法形态：v + 一位数字 + . + 一位数字 + . + 一位数字
RE_TAG_OK = re.compile(r'^v\d\.\d\.\d$')
# 每段都是纯数字、但有某段写了两位（v1.0.10）—— 用来给出更精准的提示。
RE_TAG_MULTI = re.compile(r'^v\d+\.\d+\.\d+$')

# FE_VER / BE_VER 仅供参考，读不到也不影响判定。
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
    print('（前后端版本仅供参考；三套版本互相独立，不参与标签判定）')

    if not tag:
        print('没有标签（手动触发构建），跳过形态校验。')
        return 0
    if not tag.startswith('v'):
        print('标签不以 v 开头，不是发行标签，跳过形态校验。')
        return 0

    if RE_TAG_OK.match(tag):
        print('OK：标签 %s 形态合法（v主.次.修订，每位一位数字）。' % tag)
        return 0

    if RE_TAG_MULTI.match(tag):
        msg = ('标签 %s 有一段写了两位数字 —— 每位只占一位（到 9 就进位）：'
               'v1.0.9 的下一个是 v1.1.0，不是 v1.0.10；v1.9.9 的下一个是 v2.0.0。'
               % tag)
    else:
        msg = ('标签 %s 形态不合法，应为 vX.Y.Z 且 X / Y / Z 各为一位数字（0-9），'
               '例如 v1.1.4（不要带 -rc1 之类的后缀）。' % tag)

    print('::warning title=发行标签形态不合法::%s' % msg)
    print('WARN：%s' % msg)
    return 1 if strict else 0


if __name__ == '__main__':
    sys.exit(main())
