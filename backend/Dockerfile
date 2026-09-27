# =============================================================================
# 知拾冒险社 · 后端（FastAPI）—— 微信云托管（容器方式）镜像
# -----------------------------------------------------------------------------
# 平台规范（逐条来自微信云托管官方文档：developers.weixin.qq.com/miniprogram/dev/
# wxcloudservice/wxcloudrun）：
#   1. Dockerfile 放「代码根目录」，默认名 Dockerfile；若在子目录，创建版本时
#      必须指定「构建目录 / dockerfilePath」——《概念解释》「构建目录」。
#   2. 容器**必须**监听一个端口，云托管**默认 80**；端口必须是 1~61000 的整数
#      且**不能是 9100**，「如果没有找到则部署失败」——《概念解释》「端口监听」。
#   3. 控制台/CLI 配的「监听端口」必须与容器内实际监听端口**一致**，否则请求
#      路由不进来——《概念说明》「端口监听」。
#   4. 监听地址必须是 0.0.0.0（不是 127.0.0.1），否则只有容器自己连得上；
#      平台用就绪探针（readiness probe）通过后才把流量接进来。
#   5. 多条 CMD **只有最后一条**生效（官方 FAQ）—— 这里刻意只留一条。
#   6. 基础镜像优先 LTS/稳定版；含重二进制依赖时避开 alpine，用 Debian slim
#      （官方「Dockerfile 编写」一节）。本项目带 chromadb / onnxruntime / numpy，
#      所以用 `-slim`（Debian）而不是 alpine。
#
# 构建上下文 = **backend/**（本文件与 .dockerignore 都在 backend/ 下）
#   控制台：构建目录填 `backend`，Dockerfile 路径填 `Dockerfile`。
#   CLI   ：wxcloud run:deploy --targetDir=backend --dockerfile=Dockerfile --containerPort=80
#   为什么不放仓库根：本仓库前后端同仓，根目录下的 frontend/node_modules 有两万
#   多个文件，拿它当构建上下文等于每次部署都把前端整棵树传上去。
#
# ⚠️ 为什么代码落在 /app/backend 而不是 /app —— 别「顺手」改掉
#   app/core/config.py 用 `Path(__file__).resolve().parents[3]` 反推「仓库根」，
#   再拼出 `<仓库根>/.env`。保留 backend/ 这一层，容器里的 /app 才**等价于本机
#   仓库根**，uploads/ 与 vectorstore/ 的默认位置也才落在 /app/backend/ 下
#   （与开发机逐字一致）。改成 `COPY . /app` 会让 parents[3] 解析成 `/`，
#   配置路径与数据目录一起错位。
#
# ⚠️ 依赖安装**不是**一句 `pip install -r requirements.txt`，理由见下方第 1 步。
# =============================================================================

# Python 版本：默认 3.12（**不是 3.11**，见下）
#   `backend/pyproject.toml` 声明 `requires-python = ">=3.12"`；并且 chromadb 带进来
#   的 numpy 2.5.3 元数据写着 `Requires-Python: >=3.12`。也就是说用 3.11 装不上
#   这套「2026-09-16 实测」的版本组合——pip 会把 numpy 回退到 1.26.x（本项目
#   从未实测过）。确实要换：`docker build --build-arg PYTHON_VERSION=3.11 .`
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# ---------------------------------------------------------------------------
# 运行期环境变量
# ---------------------------------------------------------------------------
# PYTHONUNBUFFERED：云托管按 stdout 采集日志（容器配置项 customLogs=stdout）。
#   不开这个，Python 会缓冲 stdout，日志会延迟甚至丢——排查线上问题时最要命。
# PYTHONDONTWRITEBYTECODE：容器里不需要 .pyc，少写磁盘。
# PYTHONFAULTHANDLER：段错误之类底层崩溃能打出 Python 栈，否则只有一句 exit 139。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# ---------------------------------------------------------------------------
# 系统层依赖：只有 libgomp1
# ---------------------------------------------------------------------------
# onnxruntime（chromadb 的传递依赖）在 Linux 上链接 libgomp.so.1，而 Debian slim
# 默认**不带** OpenMP 运行时。不装的话 `import chromadb` 会在导入期直接崩：
#   OSError: libgomp.so.1: cannot open shared object file
# 注意它的引爆条件很刁：只有 KNOWLEDGE_BASE_ENABLED=true 时才会 import chromadb
# （app/llm/kb/store.py 里是惰性导入），所以默认配置下你根本看不到这个问题，
# 等开了知识库才炸。因此下面第 3 步会**在构建期就 import 一次**把它钉住。
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# ---------------------------------------------------------------------------
# 1) 依赖层：先只 COPY requirements.txt
# ---------------------------------------------------------------------------
# 单独一层放依赖，改业务代码不会让这层缓存失效（官方推荐的构建提速手法）。
COPY requirements.txt ./

# ⚠️ 必须分两步装，不能直接 `pip install -r requirements.txt`：
#   requirements.txt 里的 `cos-python-sdk-v5==1.9.44` 元数据声明了
#   `certifi<=2021.10.8` 与 `requests<=2.27.1`（上游过度保守的旧上限），
#   正常安装会把 certifi 从 2026.07.22 **静默降级**回 2021.10.8 —— 而 certifi
#   是 httpx 的根证书包（微信 code2Session、DeepSeek、Tavily 全走它），
#   退回 2021 年的证书集是有实际风险的静默破坏，且**不会让任何测试变红**。
#   正确姿势与 backend/requirements.txt 顶部注释一致：
#     · 先把 cos-python-sdk-v5 这一行从清单里挑掉，装其余全部依赖；
#     · 再用 `--no-deps` 单独装它，它缺的传递依赖（xmltodict / crcmod /
#       pycryptodome / six）由我们点名安装、版本由我们定。
#   顺序不能反：先装 cos 再装其余依赖，certifi 会被重新拉高，看起来「没事」，
#   但哪天上游收紧约束就会变成静默降级。
RUN grep -v '^cos-python-sdk-v5' requirements.txt > /tmp/requirements.runtime.txt \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.runtime.txt \
    && pip install --no-cache-dir --no-deps cos-python-sdk-v5==1.9.44 \
    && pip install --no-cache-dir xmltodict==1.0.4 crcmod==1.7 pycryptodome==3.23.0 six \
    && rm -f /tmp/requirements.runtime.txt

# ---------------------------------------------------------------------------
# 2) 构建期自检（**别删这几行**）
# ---------------------------------------------------------------------------
# 三件事，都是「构建时红掉远比运行时才发现好」：
#   a) 把关键版本打进构建日志，云托管控制台的构建日志里能直接看到装了什么；
#   b) 断言 certifi / requests **没有**被 cos-python-sdk-v5 降级
#      （上面那条 RUN 的正面校验。这里用字符串比较就够——它防的是「退回
#        2021.10.8 / 2.27.1 这两个具体旧值」，不是通用语义化版本比较）；
#   c) 真 import 一遍关键包，其中 `chromadb` 是专门用来暴露 libgomp1 缺失的。
# 注意：**刻意不用 `pip check`** —— cos-python-sdk-v5 那两个过度保守的上限会让
# `pip check` 稳定报 2 条「不满足」，把它当闸门会让构建永久失败。
RUN python -c "from importlib.metadata import version as v; \
[print(f'{n:14s} {v(n)}') for n in ('fastapi','uvicorn','pydantic','sqlalchemy','pymysql','pyjwt','cryptography','chromadb','numpy','certifi','requests')]" \
    && python -c "import certifi, requests; \
assert certifi.__version__ > '2021.10.8', 'certifi 被 cos SDK 降级了: ' + certifi.__version__; \
assert requests.__version__ > '2.27.1', 'requests 被 cos SDK 降级了: ' + requests.__version__; \
print('no silent downgrade')" \
    && python -c "import fastapi, uvicorn, sqlalchemy, pymysql, jwt, tzdata, httpx, certifi, crcmod, xmltodict, Crypto; print('imports ok')" \
    && python -c "import chromadb; print('chromadb ok (libgomp1 present)')"

# ---------------------------------------------------------------------------
# 3) 业务代码层：改动最频繁，放最后
# ---------------------------------------------------------------------------
COPY . .

# 运行期数据目录在镜像里只留**空目录占位**：
#   · uploads/ 与 vectorstore/ 已被 .dockerignore 排除 —— 它们装的是真实用户
#     数据（本机 backend/uploads/kb/ 下现在就有一批用户上传的 .md），打进去
#     等于把用户资料烤成镜像副本；而且它们本来就该由运行环境提供。
#   · app/main.py 启动时会 mkdir uploads/avatars，但先建好更省事，
#     也避免以后换成非 root 用户时对父目录没有写权限。
RUN mkdir -p /app/backend/uploads /app/backend/vectorstore

# ---------------------------------------------------------------------------
# 安全加固（可选，默认注释掉）
# ---------------------------------------------------------------------------
# 容器当前以 **root** 运行。这不是偷懒，是因为要绑 80 端口：Linux 上 <1024 的
# 端口需要 CAP_NET_BIND_SERVICE，而云托管运行时是否放开
# `net.ipv4.ip_unprivileged_port_start` 我无法在本地验证 —— 贸然切非 root 的
# 失败形态是「版本起不来」，比以 root 跑单一用途容器更糟。
# 想切成非 root：① 控制台「监听端口」改成 >=1024（如 8080，合规，只要不是 9100）；
# ② 放开下面两行。
# RUN useradd --uid 10001 --create-home appuser && chown -R appuser:appuser /app
# USER appuser

# ---------------------------------------------------------------------------
# 4) 对外声明端口与启动命令
# ---------------------------------------------------------------------------
# EXPOSE 只是**文档性声明**，云托管并不靠它取端口 —— 真正生效的是创建版本时
# 配置的「监听端口」（默认 80）。这里写 80 是为了和下面 CMD 的默认值对齐。
EXPOSE 80

# 启动命令要点：
#   · --host 0.0.0.0 —— 必须，绑 127.0.0.1 的话外面连不进来。
#   · --port ${PORT:-80} —— 默认 80（云托管默认端口）。之所以读环境变量而不是
#     写死，是为了「控制台把端口改成别的值时不用改 Dockerfile」；两边必须一致。
#   · exec 不能省 —— 不加 exec，sh 会另起子进程，SIGTERM 传不到 uvicorn，
#     缩容/发新版时只能等超时强杀（表现为线上请求被硬切断）。
#   · --workers 1 **必须保持 1，不要为了性能调大**：
#     任务进度（app/services/task_service.py）与登录限流（app/core/ratelimit.py）
#     都是**进程内内存**。多 worker = 多份独立内存 ⇒ 轮询任务可能打到另一个
#     worker 上，表现成「出题明明成功了却报任务不存在」；限流也会各算各的。
#     同理，云托管侧的实例数建议 minNum=maxNum=1（多实例是同一个问题）。
#   · --proxy-headers / --forwarded-allow-ips —— 云托管前面有网关/LB，
#     不信任转发头的话 request.client.host 会全是网关地址。
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-80} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
