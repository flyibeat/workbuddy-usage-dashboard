# -*- coding: utf-8 -*-
"""看板服务健康检查：端口监听、扫描状态、数据新鲜度。"""
import json
import socket
import sys
import time
import urllib.request

PORT = 8791
BASE = 'http://127.0.0.1:%d' % PORT


def main():
    s = socket.socket()
    s.settimeout(1.0)
    listening = s.connect_ex(('127.0.0.1', PORT)) == 0
    s.close()
    print('端口 %d 监听: %s' % (PORT, listening))
    if not listening:
        print('服务未运行。可双击 usage-server\\重启看板服务.cmd 启动。')
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
