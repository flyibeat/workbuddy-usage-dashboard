# WorkBuddy 词元用量看板

一个**零第三方依赖**的本地用量看板：单文件 Python 后端 + 单文件 HTML 前端，只读解析 WorkBuddy 的会话记录，聚合成按天 / 月 / 模型 / 会话 / 小时的词元与积分用量视图。

```
usage_server.py   ← 后端：增量扫描 + 聚合 + HTTP 服务（纯标准库）
dashboard.html    ← 前端：单文件看板，服务按 mtime 热加载
healthcheck.py    ← 命令行健康检查
start.cmd/.sh     ← 一键启动
packaging/        ← 打包成单文件 exe
.github/workflows/ ← GitHub Actions：在云端构建 Windows / macOS / Linux 产物
```

<img width="1039" height="920" alt="1789637075369_d" src="https://github.com/user-attachments/assets/752c59f1-3f86-4fd2-a378-65e5bc194d24" />

## 特性

| 特性 | 说明 |
|---|---|
| **零依赖** | 只用 Python 标准库（`http.server` / `sqlite3` / `json`）。不需要 pip install 任何东西 |
| **增量扫描** | 按 `[mtime, size]` 签名缓存，只重解析变动的文件。首次全量约 6 秒，之后每次近乎瞬时 |
| **前端热加载** | `dashboard.html` 是独立文件。改完存盘即可，页面 30 秒内自动重载，不用重启后端 |
| **只读且克制** | 数据库以 `mode=ro` 只读 URI 打开；**从不读取会话正文**，只取用量计数与标题 |
| **跨平台** | Windows / macOS / Linux 通用。数据根四级 fallback，以服务 / 计划任务等非交互身份运行也能自动定位 |
| **可打包** | 一条命令打成单文件 exe，拷走即用（约 9.8 MB） |
| **默认只听本机** | 默认绑定 `127.0.0.1`，不对外暴露 |

## 快速开始

**前置条件**：本机已安装 WorkBuddy，且 `~/.workbuddy/projects/` 下存在会话数据。

### 方式一：直接跑源码

```bash
# Windows：双击 start.cmd
# macOS / Linux：
./start.sh

# 或者手动
python3 usage_server.py
```

### 方式二：构建成单文件 exe

```bash
pip install pyinstaller
python packaging/build_exe.py
# 产物：dist/wb-usage.exe（非 Windows 为 dist/wb-usage），约 9.8 MB，零运行时依赖
```

打包完成后 `wb-usage.exe` 可以拷到任意目录直接双击运行，不依赖 Python 环境：

```powershell
.\wb-usage.exe --open          # 启动并自动打开浏览器
.\wb-usage.exe --port 8800     # 换端口
```

然后浏览器打开 <http://127.0.0.1:8791>。

## 数据来源

程序只读两处，**全部位于 WorkBuddy 的数据目录**：

| 来源 | 用途 | 取哪些字段 |
|---|---|---|
| `~/.workbuddy/projects/**/*.jsonl` | 逐行累计用量 | `usage` / `rawUsage` / `providerData` 下的 `inputTokens`、`outputTokens`、`totalTokens`、`prompt_cache_hit_tokens`；以及 `model` / `requestModelName` / `timestamp` / `credit` |
| `~/.workbuddy/workbuddy.db` | 补会话标题与工作目录 | 只读 `select id, title, custom_title, cwd from sessions`、`select session_id, credit_json from session_usage`。**不读 `messages` / `content` 正文** |

> **缓存里存什么**：`scan-cache.json` 只存 `{绝对路径: {"sig": [mtime, size], "recs": [[数字…]]}}` —— 纯数字数组，**连会话标题与 cwd 都不落盘**。

### 数据根定位（四级 fallback）

程序不硬编码数据目录，按以下顺序定位；这解决了「以服务 / 计划任务等非交互身份运行时读不到数据」的经典问题：

| 级 | 条件 | 来源标记 |
|---|---|---|
| 1 | 设了 `WB_USAGE_HOME`（或命令行 `--home`） | `WB_USAGE_HOME` |
| 2 | `~/.workbuddy` 存在 | `用户目录` |
| 3 | 以上都不成立 → 自动探测 `<盘>:\Users\*\.workbuddy`（POSIX 为 `/Users/*`、`/home/*`）。命中多个时先按 `USERNAME` 同名择优，再按会话文件数择优 | `自动探测（唯一命中）` / `自动探测（按用户名）` / `自动探测（按数据量）` |
| 4 | 都没找到 | 回退并打印自检块 |

扫到 0 个文件时会打印**自检块**：选中的数据根、判定来源、程序目录、相关环境变量、探测过的全部候选项（标注「有数据 / 不存在」）以及两种修法。**不会静默返回空数据。**

## 配置

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WB_USAGE_HOME` | （空） | 显式指定 WorkBuddy 数据目录。可指向 `~/.workbuddy` 本身或其上级 |
| `WB_USAGE_PORT` | `8791` | 监听端口 |
| `WB_USAGE_BIND` | `127.0.0.1` | 绑定地址。**改成 `0.0.0.0` 会让同网段任何人都能读到你的会话标题与工作目录** |
| `WB_USAGE_REFRESH` | `60` | 后台重扫间隔（秒） |
| `WB_USAGE_META_TTL` | `300` | 会话标题/目录元数据的缓存时长（秒） |

### 命令行参数

| 参数 | 说明 |
|---|---|
| `--port N` | 临时换端口，等价于 `WB_USAGE_PORT` |
| `--home PATH` | 临时指定数据目录，等价于 `WB_USAGE_HOME` |
| `--open` | 启动后自动打开浏览器（后台常驻时不要加） |
| `--rebuild` | 忽略缓存，强制全量重扫 |
| `--version` | 只打印版本号后退出 |

## 版本号

**前后端各自计版本，互不牵连。**

| 组件 | 版本号写在哪 | 什么时候升它 |
|---|---|---|
| 前端（看板页面） | `dashboard.html` 里的 `var FE_VER='v1.0.1';` | 只改了 `dashboard.html` |
| 后端（数据服务） | `usage_server.py` 里的 `BE_VER = ... or 'v1.0.1'` | 只改了 `usage_server.py` |
| 两边都改了 | 两个都升 | — |

为什么分开计：`dashboard.html` 是一个可以**单独热替换**的独立文件（程序目录下放一份就覆盖内嵌的那份，改完存盘即生效），它可以独立于后端演进。用一个版本号捆住两者，只会出现「前端改了但版本没动」或「为了升前端版本不得不动后端」这类别扭事。

页面页头会同时显示两者，一眼看出当前跑的是哪个组合：

```
页面版本 v1.0.1 ｜ 服务版本 v1.0.1
```

- **前端版本**由页面自己携带（`FE_VER`），因为它就是那个文件的一部分
- **后端版本**经 `GET /api/data` 的 `serverVersion` 字段送到页面
- `WB_VERSION` 环境变量可临时覆盖后端版本，**仅供验证/临时构建**，日常不要设 —— 版本号跟着代码走才不会各说各话

发布用的 git 标签与版本号的关系：一个标签无法同时等于两个版本号，所以 CI 的判定标准是「**标签至少等于其中一个**」。一个都对不上会在 Actions 里打一条 warning（不拦发布），提示你可能忘了升版本号。

## HTTP 接口

| 路径 | 说明 |
|---|---|
| `GET /` | 看板页面。优先用程序目录下的 `dashboard.html`，没有则用内嵌副本 |
| `GET /api/data` | 完整聚合数据（`days` / `months` / `models` / `sessions` / `hours` / `recordCount` / `source` / `htmlMtime` / `serverVersion`） |
| `GET /api/health` | 运行状态（`records` / `files` / `error` / `scanSeconds` / `dataRoot` / `dataRootSource` / `building` / `version`） |

**没有内置鉴权。** 安全性依赖默认只绑 `127.0.0.1`。若要对外提供，请在前面套一层带鉴权的反向代理。

## 关于打包

`packaging/build_exe.py` 是 PyInstaller 的 onefile 封装，已经排除了 `tkinter` / `unittest` / `pydoc` / `doctest` / `lib2to3` / `test` / `distutils` / `setuptools` / `pip` 等无用模块，把体积从约 14 MB 压到约 9.8 MB。

设计要点：`dashboard.html` 用 `--add-data` 打进 exe 作**兜底**；程序目录下若另有 `dashboard.html`，那个优先 —— 这样打包后仍能热改前端，不必重新打包。

## 用 GitHub Actions 云构建（本机不用装 Python 和 PyInstaller）

仓库里已经带了 `.github/workflows/build.yml`，推上去即可用。Windows / macOS / Linux 三平台在 GitHub 的机器上并行构建，产物直接下载。

### 方式一：手动构建

**Actions → 左侧选 `Build` → 右上 `Run workflow` → 选分支 → `Run workflow`**。

约 1~2 分钟后任务变绿，进入这次运行页面，最下方 **Artifacts** 区域可以下载：

```
build-windows-latest   →  wb-usage.exe
build-ubuntu-latest    →  wb-usage
build-macos-latest     →  wb-usage
```

下载下来是个 zip，解压即得可执行文件。**Artifact 默认保留 90 天。**

### 方式二：打标签，自动发 Release

先按上文「版本号」一节升好对应组件的版本号，再打标签：

```bash
git tag v1.0.1
git push origin v1.0.1
```

workflow 会自动构建三个平台，并在全部构建成功**之后**创建一个 Release，附上三份重命名好的产物：

```
wb-usage-windows-x64.exe
wb-usage-linux-x64
wb-usage-macos-arm64
```

适合发版本给别人用。（为什么不在各平台的 job 里直接传 Release：Linux 与 macOS 的产物默认同名 `wb-usage`，并发上传会撞名，也会抢写同一个 Release —— 所以把发版单独拆成一个 job。）

### CI 里做了什么

| 步骤 | 说明 |
|---|---|
| `actions/setup-python@v5` | 装 Python 3.13 |
| `pip install pyinstaller` | 装打包工具 |
| `python packaging/build_exe.py` | 出单文件产物（Windows 是 `.exe`，其余无后缀） |
| 冒烟测试 | 后台起进程 → 轮询 `/api/health` → 打印结果 → 杀进程。**CI 机器上没有 WorkBuddy 数据，`records=0` 是正常的**；这一步真正的作用是确认二进制能起来、端口能绑、接口能应答（即没有"打包后运行期炸"） |
| `upload-artifact` | 上传产物（名字 `build-<os>`），找不到文件会直接报错，不会静默通过 |
| `packaging/check_version.py` | 在 `release` job 里校验标签与 `FE_VER` / `BE_VER` 是否对得上，对不上打 warning（不拦发布） |
| 独立的 `release` job | 仅当 ref 是 tag 时运行：等三个平台**全部**构建完 → 下载 artifact → 重命名成平台专属文件名 → 一次性创建 Release |

> 无论用哪种方式，**产物跑起来后请以 `/api/health` 的 `records > 0` 为准**判断数据是否正常，而不是以进程状态为准。


## 让它常驻后台

程序本身是前台进程，关掉窗口即退出。想让它一直跑，用任何进程管理器挂它都行，不需要改代码：

- **Windows**：用 [NSSM](https://nssm.cc/) 注册成服务 —— `nssm install wb-usage "C:\path\to\wb-usage.exe"`，然后把启动目录（AppDirectory）设成 exe 所在目录即可。注意服务账户的 `USERPROFILE` 与你的交互账户不同，程序会按上文四级 fallback 自动探测数据目录；探测不准时用 `WB_USAGE_HOME` 显式指定。
- **macOS**：写个 `launchd` plist，或干脆 `nohup ./wb-usage &`
- **Linux**：写个 systemd user unit

无论用哪种方式托管，有两个坑值得留意：

1. **「已停止」不等于进程已经退出。** 端口可能还被上一次的进程占着，此时覆盖文件会成功，但新实例绑不上端口而直接退出 —— 表面上「重启成功」，实际跑的还是旧版本。
2. **「进程在运行」不等于「数据正常」。** 请以 `/api/health` 的 `records > 0` 为准，而不是以进程状态为准。

## 排错

### 页面能打开，但所有数字都是 0

**先看日志首行的「数据源」路径有没有展开成真实路径**，别急着查端口：

```
启动中，端口 127.0.0.1:8791，数据源 C:\Users\<你>\.workbuddy\projects    ← 正常
启动中，端口 127.0.0.1:8791，数据源 ~\.workbuddy\projects                 ← 没展开 = 定位失败
```

若日志里出现自检块，它已经列出了全部候选项和修法。也可以直接查接口：

```bash
curl http://127.0.0.1:8791/api/health
# records=0 且 error 为 null，同时 files=0  → 数据根没定位对
```

### 端口被占用

后端会打一条日志后以非零码退出。用 `--port` 换口，或先找出占用者：

```powershell
Get-NetTCPConnection -LocalPort 8791 -State Listen | ForEach-Object {
  Get-Process -Id $_.OwningProcess
}
```

### 改了代码却不生效

先确认端口真正释放了，再谈「重启」。被其他进程托管时尤其容易踩：停止托管进程不一定终止它拉起的子进程，上次的实例还在服务旧代码，新实例因端口被占直接退出。

## 隐私说明

- 只读，不修改 WorkBuddy 的任何文件。
- **不读取会话正文**（`messages` / `content` 字面引用 0 处）。
- 磁盘缓存 `scan-cache.json` 只存**纯数字**数组与文件路径，不存标题、不存工作目录。
- 无任何遥测与外部请求：源码中的 URL 只有 `http://127.0.0.1:*`，不访问互联网。
- 无内置鉴权，默认只绑 `127.0.0.1`。

## License

MIT，见 [LICENSE](LICENSE)。
