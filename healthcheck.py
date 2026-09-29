# -*- coding: utf-8 -*-
"""看板服务健康检查：端口监听、扫描状态、数据新鲜度。

端口优先级：--port 参数 > 环境变量 WB_USAGE_PORT > 默认 8791。
（服务端本就支持 `--port` 与 WB_USAGE_PORT，体检脚本跟着走，
免得改了绑定就一律误报「服务未运行」。）
"""
import json
import os
import socket
import sys
import time
import urllib.request

DEFAULT_PORT = 8791


def _resolve_port(argv):
    if '--port' in argv:
        i = argv.index('--port')
        if i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                print('--port 参数无效，沿用默认 %d' % DEFAULT_PORT)
        else:
            print('--port 后缺少数值，沿用默认 %d' % DEFAULT_PORT)
    try:
        return int(os.environ.get('WB_USAGE_PORT', DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


PORT = _resolve_port(sys.argv[1:])
BASE = 'http://127.0.0.1:%d' % PORT


def main():
    s = socket.socket()
    s.settimeout(1.0)
    listening = s.connect_ex(('127.0.0.1', PORT)) == 0
    s.close()
    print('端口 %d 监听: %s' % (PORT, listening))
    if not listening:
        print('服务未运行。可双击 start.cmd 启动（macOS/Linux：./start.sh）。')
        return 1
    try:
        with urllib.request.urlopen(BASE + '/api/health', timeout=5) as f:
            h = json.loads(f.read().decode('utf-8'))
        lag = time.time() - (h.get('builtAt') or 0)
        print('已解析文件: %d  记录数: %d' % (h.get('files') or 0, h.get('records') or 0))
        print('上次扫描: %.0f 秒前（耗时 %.2fs）' % (lag, h.get('scanSeconds') or 0))
        print('正在扫描: %s' % h.get('building'))
        print('错误: %s' % (h.get('error') or '无'))
        with urllib.request.urlopen(BASE + '/api/data', timeout=20) as f:
            d = json.loads(f.read().decode('utf-8'))
        days = d.get('days') or []
        if days:
            last = days[-1]
            print('最新一天 %s：请求 %d 次，总词元 %s' % (last['date'], last['req'], format(last['total'], ',')))
        print('页面: %s/' % BASE)
        return 0 if not h.get('error') else 2
    except Exception as e:
        print('请求失败: %r' % e)
        return 1


if __name__ == '__main__':
    sys.exit(main())
