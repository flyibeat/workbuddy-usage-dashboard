# -*- coding: utf-8 -*-
"""WorkBuddy 每日词元用量看板 —— 本机常驻服务

数据源：~/.workbuddy/projects/<工作目录>/<会话ID>.jsonl
        每行助手响应的 providerData.usage / rawUsage 含词元与积分。

启动：
    python usage_server.py
    浏览器打开 http://127.0.0.1:8791

特性：
    * 启动全量扫描一次，之后每 REFRESH_SEC 秒做增量扫描（按 mtime+size 跳过未变文件）
    * 扫描缓存落盘，重启秒级恢复
    * 纯标准库，不联网，只监听 127.0.0.1
"""
import os
import sys
import json
import glob
import time
import threading
import datetime
import collections
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ---- 数据根定位 -------------------------------------------------------------
#
# 数据固定放在「数据根」下：<数据根>/projects/*/*.jsonl 与 <数据根>/workbuddy.db，
# 数据根就是用户目录里的 .workbuddy。
#
# 为什么不直接写 os.path.expanduser('~')：
#   Windows 上 expanduser 只认 USERPROFILE。注册成服务（LocalSystem）跑时，
#   该变量指向服务账户自己的 profile，于是程序去空目录里找数据 —— 服务在跑、
#   端口在听、日志在写，可看板上每个数字都是 0，且不报任何错，极易误判成
#   「数据没同步」。所以这里做四级定位，越靠前越优先：
#
#     1. WB_USAGE_HOME 环境变量  —— 显式指定，写错也尊重（会告警）
#     2. ~/.workbuddy 存在       —— 普通场景走这条，行为与旧版完全一致
#     3. 自动探测                —— 扫各用户目录，唯一命中即采用；多个命中按
#                                  用户名匹配、再按会话数择优
#     4. 回退 ~/.workbuddy       —— 与旧版行为相同，并由自检块给出诊断
#
# 第 3 级跨平台（Windows 的 <盘>:\Users、macOS 的 /Users、Linux 的 /home），
# 所以它不只服务这一台机器 —— 换机、换系统都不必再想起这件事。

def _normpath(p):
    return os.path.normcase(os.path.normpath(p))


def _looks_like_wb(d):
    """目录是否像 WorkBuddy 的数据根（有 projects/ 或 workbuddy.db）。"""
    if not d or not os.path.isdir(d):
        return False
    return (os.path.isdir(os.path.join(d, 'projects'))
            or os.path.isfile(os.path.join(d, 'workbuddy.db')))


def _count_jsonl(d, cap=500):
    """会话文件数，只用作多候选时的择优依据。"""
    n = 0
    try:
        for sub in os.listdir(os.path.join(d, 'projects')):
            n += len(glob.glob(os.path.join(d, 'projects', sub, '*.jsonl')))
            if n >= cap:
                return cap
    except Exception:
        pass
    return n


def _wb_score(d):
    """可信度：先看是否与当前用户同名（服务场景下 USERNAME 仍会带上），再看数据量。"""
    owner = os.path.basename(os.path.dirname(d)).lower()
    me = (os.environ.get('USERNAME') or os.environ.get('USER') or '').lower()
    return (1 if (me and owner == me) else 0, _count_jsonl(d))


def _profile_containers():
    """可能存放 <用户名> 目录的容器。"""
    if os.name == 'nt':
        out, seen = [], set()
        drives = [os.environ.get('SystemDrive', 'C:')]
        drives += [c + ':' for c in 'DEFGHIJKLMNOPQRSTUVWXYZ']
        for drv in drives:
            p = os.path.join(drv + os.sep, 'Users')
            k = _normpath(p)
            if k not in seen and os.path.isdir(p):
                seen.add(k)
                out.append(p)
        return out
    return [p for p in ('/Users', '/home') if os.path.isdir(p)]


def _resolve_data_root():
    """返回 (数据根, 来源说明, 探测过的候选列表)。"""
    # 1) 显式指定：WB_USAGE_HOME（或命令行 --home 灌进来的同名变量）
    env = (os.environ.get('WB_USAGE_HOME') or '').strip().strip('"').strip("'")
    if env:
        env = os.path.expandvars(env)
        got = os.path.abspath(env)
        if _looks_like_wb(got):
            return got, 'WB_USAGE_HOME', []
        sub = os.path.join(got, '.workbuddy')
        if _looks_like_wb(sub):
            return sub, 'WB_USAGE_HOME（自动补 .workbuddy）', []
        return got, 'WB_USAGE_HOME（该路径不存在）', []

    # 2) 常规展开 —— 非服务场景全部走这条，与改造前完全一致
    try:
        _home = os.path.expanduser('~')
    except Exception:
        _home = ''
    if not _home or _home == '~':
        # 展开不出来（USERPROFILE/HOME 都没了）时，别再产出字面量 '~\.workbuddy'
        _home = os.environ.get('USERPROFILE') or os.environ.get('HOME') or ''
    default = os.path.join(_home, '.workbuddy') if _home else os.path.join('.', '.workbuddy')
    if _looks_like_wb(default):
        return default, '用户目录', []

    # 3) 自动探测
    cands = [default]
    for cont in _profile_containers():
        try:
            for name in sorted(os.listdir(cont)):
                cands.append(os.path.join(cont, name, '.workbuddy'))
        except Exception:
            continue
    for k in ('USERPROFILE', 'HOME'):
        v = os.environ.get(k)
        if v:
            cands.append(os.path.join(v, '.workbuddy'))
    uniq, seen = [], set()
    for c in cands:
        k = _normpath(c)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    hits = [c for c in uniq if _looks_like_wb(c)]
    if len(hits) == 1:
        return hits[0], '自动探测（唯一命中）', uniq
    if len(hits) > 1:
        hits.sort(key=_wb_score, reverse=True)
        return hits[0], '自动探测（%d 个候选，按用户名/会话数择优）' % len(hits), uniq

    # 4) 回退：行为等同旧版，由自检块负责解释
    return default, '回退默认（未找到任何数据根）', uniq


# --home 必须在解析之前就灌进环境变量，才不影响模块级求值顺序
if '--home' in sys.argv:
    _i = sys.argv.index('--home')
    if _i + 1 < len(sys.argv):
        os.environ['WB_USAGE_HOME'] = sys.argv[_i + 1]

WB, WB_SOURCE, WB_CANDIDATES = _resolve_data_root()
HOME = os.path.dirname(WB)
PROJECTS = os.path.join(WB, 'projects')
DB = os.path.join(WB, 'workbuddy.db')


def _exe_dir():
    """程序目录。打包成 exe 时是 exe 所在目录，否则是本脚本目录。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _res_dir():
    """内嵌资源的解压目录。PyInstaller onefile 解到 sys._MEIPASS —— 那是**临时**
    目录、进程退出即删，所以只能放随包资源，绝不能放缓存和日志。"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', _exe_dir())
    return os.path.dirname(os.path.abspath(__file__))


APPDIR = _exe_dir()          # 数据落这里：缓存、日志、可选的外部前端
RESDIR = _res_dir()          # 随包资源读这里：内嵌的 dashboard.html 兜底副本
CACHE_PATH = os.path.join(APPDIR, 'scan-cache.json')
LOG_PATH = os.path.join(APPDIR, 'server.log')
PORT = int(os.environ.get('WB_USAGE_PORT', '8791'))
BIND = os.environ.get('WB_USAGE_BIND', '127.0.0.1')
REFRESH_SEC = int(os.environ.get('WB_USAGE_REFRESH', '60'))
# 会话标题（来自 workbuddy.db）的缓存时长，秒。标题很少变，读库不必每次刷新都开。
SESSION_META_TTL = int(os.environ.get('WB_USAGE_META_TTL', '300'))

_LOCK = threading.Lock()
_meta_cache = {'at': 0.0, 'map': {}}
_STATE = {
    'data': None,
    'built_at': None,
    'scan_seconds': None,
    'files': 0,
    'records': 0,
    'error': None,
    'building': False,
}


def log(msg):
    line = '[%s] %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    try:
        print(line, flush=True)
    except Exception:
        # 计划任务 / pythonw 等无有效标准输出时静默
        pass
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')
    except Exception:
        pass


_EMPTY_WARNED = {'done': False}


def _warn_empty_scan():
    """扫到 0 个会话文件时说清原因 —— 这种故障的全部特征就是「一切正常但数字是 0」，
    光看服务状态和端口永远查不出来，所以直接把定位过程打出来。每个进程只报一次。"""
    if _EMPTY_WARNED['done']:
        return
    _EMPTY_WARNED['done'] = True
    log('-' * 62)
    log('未扫到任何会话文件，看板会是空的。定位信息：')
    log('  选中的数据根 : %s' % WB)
    log('  判定来源     : %s' % WB_SOURCE)
    log('  程序目录     : %s' % APPDIR)
    for k in ('USERPROFILE', 'USERNAME', 'HOME', 'USER'):
        v = os.environ.get(k)
        if v:
            log('  环境变量 %-11s= %s' % (k, v))
    if WB_CANDIDATES:
        log('  探测过的候选：')
        for c in WB_CANDIDATES[:15]:
            log('    [%s] %s' % ('有数据' if _looks_like_wb(c) else '不存在 ', c))
        if len(WB_CANDIDATES) > 15:
            log('    …另有 %d 个' % (len(WB_CANDIDATES) - 15))
    ex = r'C:\Users\<用户名>\.workbuddy' if os.name == 'nt' else '/Users/<用户名>/.workbuddy'
    log('  修法：把数据根指对，二者等价 ——')
    log('    环境变量  WB_USAGE_HOME=%s' % ex)
    log('    命令行    wb-usage.exe --home "%s"' % ex)
    log('-' * 62)


# ---------------------------------------------------------------- 扫描与解析

def parse_file(fp):
    """解析单个 jsonl，返回按请求的记录列表。坏行跳过。"""
    recs = []
    try:
        fh = open(fp, 'r', encoding='utf-8', errors='ignore')
    except Exception:
        return recs
    with fh:
        for line in fh:
            if '"providerData"' not in line or '"usage"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            pd = o.get('providerData')
            if not isinstance(pd, dict):
                continue
            u = pd.get('usage')
            if not isinstance(u, dict):
                continue
            ts = o.get('timestamp')
            if not ts:
                continue
            if ts > 1e12:
                ts = ts / 1000.0
            raw = pd.get('rawUsage') or {}
            inp = int(u.get('inputTokens') or 0)
            out = int(u.get('outputTokens') or 0)
            tot = int(u.get('totalTokens') or 0) or (inp + out)
            cached = int(raw.get('prompt_cache_hit_tokens') or 0)
            recs.append([
                ts,
                pd.get('model') or pd.get('requestModelName') or '未知',
                inp, out, tot, cached,
                float(raw.get('credit') or 0),
            ])
    return recs


def load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as fh:
            obj = json.load(fh)
        if isinstance(obj, dict) and obj.get('v') == 1:
            return {k: v for k, v in (obj.get('files') or {}).items()}
    except Exception:
        pass
    return {}


def save_cache(cache):
    tmp = CACHE_PATH + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'v': 1, 'files': cache}, fh, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception as e:
        log('缓存写入失败: %s' % e)


def scan(cache):
    """增量扫描，返回 (cache, records, 解析过的文件数)"""
    files = glob.glob(os.path.join(PROJECTS, '*', '*.jsonl'))
    new_cache = {}
    records = []
    parsed = 0
    for fp in files:
        try:
            st = os.stat(fp)
        except Exception:
            continue
        sig = [int(st.st_mtime), int(st.st_size)]
        ent = cache.get(fp)
        if ent and list(ent.get('sig') or []) == sig:
            recs = ent.get('recs') or []
        else:
            recs = parse_file(fp)
            parsed += 1
        new_cache[fp] = {'sig': sig, 'recs': recs}
        sid = os.path.basename(fp)[:-6]
        for r in recs:
            records.append((sid,) + tuple(r))
    return new_cache, records, parsed


# ---------------------------------------------------------------- 聚合

def agg(records):
    day = collections.defaultdict(collections.Counter)
    day_model = collections.defaultdict(collections.Counter)
    day_hour = collections.defaultdict(collections.Counter)
    ses = collections.defaultdict(collections.Counter)
    month = collections.defaultdict(collections.Counter)
    n = 0
    tmin = tmax = None
    for sid, ts, model, inp, out, tot, cached, credit in records:
        n += 1
        dt = datetime.datetime.fromtimestamp(ts)
        d = dt.strftime('%Y-%m-%d')
        c = day[d]
        c['req'] += 1
        c['input'] += inp
        c['output'] += out
        c['total'] += tot
        c['cached'] += cached
        c['credit'] += credit
        c['fresh'] += (inp - cached if inp > cached else 0)
        m = day_model[(d, model)]
        m['req'] += 1
        m['total'] += tot
        m['output'] += out
        m['cached'] += cached
        m['fresh'] += (inp - cached if inp > cached else 0)
        m['credit'] += credit
        h = day_hour[(d, dt.strftime('%H'))]
        h['req'] += 1
        h['input'] += inp
        h['output'] += out
        h['total'] += tot
        h['cached'] += cached
        h['fresh'] += (inp - cached if inp > cached else 0)
        h['credit'] += credit
        s = ses[sid]
        s['req'] += 1
        s['total'] += tot
        s['output'] += out
        s['credit'] += credit
        mm = month[d[:7]]
        mm['req'] += 1
        mm['input'] += inp
        mm['output'] += out
        mm['total'] += tot
        mm['cached'] += cached
        mm['credit'] += credit
        tmin = ts if tmin is None or ts < tmin else tmin
        tmax = ts if tmax is None or ts > tmax else tmax

    days = []
    for k in sorted(day):
        c = dict(day[k])
        days.append({'date': k, **c})

    models = [{'date': k[0], 'model': k[1], **dict(v)}
              for k, v in sorted(day_model.items())]

    # 会话维度：带上标题与工作目录，免得前端只能显示看不懂的会话 ID
    meta = load_session_meta()
    sessions = []
    for k, v in ses.items():
        m = meta.get(k) or {}
        item = {
            'session': k,
            'title': m.get('custom') or m.get('title') or '',
            'cwd': m.get('cwd') or '',
        }
        item.update(dict(v))
        sessions.append(item)
    sessions = sorted(sessions, key=lambda x: -x['total'])[:60]

    months = [{'month': k, **dict(v)} for k, v in sorted(month.items())]

    hours = [{'date': k[0], 'hour': k[1], **dict(v)}
             for k, v in sorted(day_hour.items())]

    return {
        'generatedAt': datetime.datetime.now().isoformat(timespec='seconds'),
        'source': PROJECTS,
        'span': {
            'from': datetime.datetime.fromtimestamp(tmin).isoformat(timespec='seconds') if tmin else None,
            'to': datetime.datetime.fromtimestamp(tmax).isoformat(timespec='seconds') if tmax else None,
        },
        'days': days,
        'months': months,
        'models': models,
        'sessions': sessions,
        'hours': hours,
        'recordCount': n,
        'reconcile': reconcile(ses),
    }


def load_session_meta(force=False):
    """读 workbuddy.db 的 sessions 表，取会话标题与工作目录。

    用途：看板上「单会话消耗」原先只显示会话 ID，人看不懂 ID 对应哪次对话，
    所以把标题（custom_title 优先，用户手动改名过的以它为准）一起下发。

    缓存 SESSION_META_TTL 秒；读库失败不影响主流程 —— 返回空表，
    前端会退回显示会话 ID，统计数字不受任何影响。
    """
    now = time.time()
    if not force and _meta_cache['map'] and now - _meta_cache['at'] < SESSION_META_TTL:
        return _meta_cache['map']
    if not os.path.exists(DB):
        return _meta_cache['map'] or {}
    try:
        con = sqlite3.connect('file:' + DB.replace('\\', '/') + '?mode=ro', uri=True)
        rows = con.execute('select id, title, custom_title, cwd from sessions').fetchall()
        con.close()
    except Exception as e:
        log('读取会话标题失败（不影响统计）：%r' % e)
        return _meta_cache['map'] or {}
    out = {}
    for sid, title, custom, cwd in rows:
        out[sid] = {'title': title or '', 'custom': custom or '', 'cwd': cwd or ''}
    _meta_cache['at'] = now
    _meta_cache['map'] = out
    return out


def reconcile(ses):
    """与 workbuddy.db 的 session_usage.credit_json 对账，仅作数据完整性自检。"""
    out = {'checked': 0, 'match': 0, 'mismatch': 0, 'missing': 0}
    if not os.path.exists(DB):
        return out
    try:
        con = sqlite3.connect('file:' + DB.replace('\\', '/') + '?mode=ro', uri=True)
        rows = con.execute('select session_id, credit_json from session_usage').fetchall()
        con.close()
    except Exception:
        return out
    for sid, cj in rows:
        if not cj:
            continue
        try:
            lib = sum(float(v) for v in json.loads(cj).values())
        except Exception:
            continue
        mine = ses.get(sid, {}).get('credit', 0.0)
        out['checked'] += 1
        if mine <= 0 and lib > 0:
            out['missing'] += 1
        elif abs(mine - lib) <= max(0.05, lib * 0.001):
            out['match'] += 1
        else:
            out['mismatch'] += 1
    return out


# ---------------------------------------------------------------- 刷新线程

def build(force_full=False):
    started = time.time()
    with _LOCK:
        _STATE['building'] = True
    try:
        cache = {} if force_full else load_cache()
        new_cache, records, parsed = scan(cache)
        save_cache(new_cache)
        data = agg(records)
        with _LOCK:
            _STATE.update({
                'data': data,
                'built_at': time.time(),
                'scan_seconds': round(time.time() - started, 2),
                'files': len(new_cache),
                'records': len(records),
                'error': None,
            })
        log('刷新完成：%d 文件（重解析 %d）/ %d 条记录 / 耗时 %.1fs'
            % (len(new_cache), parsed, len(records), time.time() - started))
        if not new_cache:
            _warn_empty_scan()
    except Exception as e:
        with _LOCK:
            _STATE['error'] = repr(e)
        log('刷新失败：%r' % e)
    finally:
        with _LOCK:
            _STATE['building'] = False


def refresher():
    while True:
        try:
            build()
        except Exception as e:
            log('刷新线程异常：%r' % e)
        time.sleep(REFRESH_SEC)


# ---------------------------------------------------------------- 看板前端

def html_path():
    """前端文件位置。**优先用程序目录下的外部 dashboard.html** —— 打包成 exe 后前端
    仍是普通文件，改完存盘 + 刷新浏览器即生效，不必重新打包；没有外部文件才退回
    随包内嵌的那份。"""
    ext = os.path.join(APPDIR, 'dashboard.html')
    if os.path.exists(ext):
        return ext
    emb = os.path.join(RESDIR, 'dashboard.html')
    return emb if os.path.exists(emb) else ext


_html_cache = {'mtime': None, 'body': ''}


def html_mtime():
    """前端文件的修改时间，作为版本号下发给页面，用于自动重载。"""
    try:
        return int(os.stat(html_path()).st_mtime)
    except Exception:
        return 0


def load_html():
    """前端页面独立存放，改动后只要存盘 + 刷新浏览器即生效，不必重启服务。"""
    try:
        st = os.stat(html_path())
    except Exception as e:
        return ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<title>frontend missing</title></head>'
                '<body style="font-family:sans-serif;padding:40px">'
                '<h2>dashboard.html not found</h2><pre>%s</pre></body></html>' % e)
    if _html_cache['mtime'] != st.st_mtime or not _html_cache['body']:
        with open(html_path(), 'r', encoding='utf-8') as fh:
            _html_cache['body'] = fh.read()
        _html_cache['mtime'] = st.st_mtime
    return _html_cache['body']


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = 'WBUsage/1.0'

    def _send(self, code, body, ctype):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html', '/dashboard'):
            self._send(200, load_html(), 'text/html; charset=utf-8')
            return
        if path == '/api/data':
            force = 'force=1' in self.path
            if force:
                threading.Thread(target=build, daemon=True).start()
            with _LOCK:
                data = _STATE['data']
                busy = _STATE['building']
                err = _STATE['error']
            if data is None:
                self._send(200, json.dumps({'generatedAt': '', 'days': [], 'months': [],
                                            'models': [], 'sessions': [], 'hours': [],
                                            'recordCount': 0, 'refreshSec': REFRESH_SEC,
                                            'scanError': err or '首次扫描进行中，请稍后刷新'},
                                           ensure_ascii=False), 'application/json; charset=utf-8')
                return
            out = dict(data)
            out['refreshSec'] = REFRESH_SEC
            out['building'] = busy
            out['scanError'] = err
            out['htmlMtime'] = html_mtime()
            self._send(200, json.dumps(out, ensure_ascii=False), 'application/json; charset=utf-8')
            return
        if path == '/api/health':
            with _LOCK:
                st = {'records': _STATE['records'], 'files': _STATE['files'],
                      'builtAt': _STATE['built_at'], 'error': _STATE['error'],
                      'scanSeconds': _STATE['scan_seconds'], 'building': _STATE['building'],
                      'dataRoot': WB, 'dataRootSource': WB_SOURCE}
            self._send(200, json.dumps(st, ensure_ascii=False), 'application/json; charset=utf-8')
            return
        self._send(404, 'not found', 'text/plain; charset=utf-8')

    def log_message(self, fmt, *args):
        pass


def _pause_if_interactive():
    """双击运行出错时留住窗口，免得报错一闪而过；作为计划任务运行时不会阻塞。"""
    try:
        if sys.stdin and sys.stdin.isatty():
            input('按回车键退出...')
    except Exception:
        pass


def main():
    global PORT
    # 命令行可覆盖端口，方便打包后双击临时换口：wb-usage.exe --port 8800
    if '--port' in sys.argv:
        try:
            PORT = int(sys.argv[sys.argv.index('--port') + 1])
        except Exception:
            log('--port 参数无效，沿用 %d' % PORT)
    frozen = getattr(sys, 'frozen', False)
    log('启动中，端口 %s:%d，数据源 %s' % (BIND, PORT, PROJECTS))
    log('数据根判定：%s（来源：%s）' % (WB, WB_SOURCE))
    if frozen:
        log('程序目录 %s ｜ 资源目录 %s' % (APPDIR, RESDIR))
    build(force_full=('--rebuild' in sys.argv))
    threading.Thread(target=refresher, daemon=True).start()
    try:
        srv = ThreadingHTTPServer((BIND, PORT), Handler)
    except OSError as e:
        log('端口 %d 绑定失败：%s' % (PORT, e))
        log('可能已有一个实例在跑。换端口：设环境变量 WB_USAGE_PORT，或用 --port 8800')
        _pause_if_interactive()
        raise SystemExit(1)
    url = 'http://%s:%d' % ('127.0.0.1' if BIND in ('0.0.0.0', '') else BIND, PORT)
    log('服务就绪：%s' % url)
    if frozen:
        print('')
        print('  WorkBuddy 用量看板已启动')
        print('  浏览器打开：%s' % url)
        print('  数据根：%s' % WB)
        print('  关闭本窗口即停止服务；缓存与日志都写在同目录下。')
        print('')
        if '--open' in sys.argv:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log('收到中断，退出')
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
