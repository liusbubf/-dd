# 前端镜像 —— X86 云手机平台 管理系统（Vue3 + Vite -> nginx）
# 重要：本 Dockerfile 的构建上下文是「仓库根目录」（见 docker-compose.yml 的
#       frontend.build.context: .），这样才能同时 COPY frontend 源码与
#       deploy/nginx/default.conf。单独构建时请：
#           docker build -f frontend/Dockerfile -t cloud-frontend .
# ---------------------------------------------------------------------------

# ---------- 构建阶段：node:22 打包出静态产物 dist ----------
# 必须 >= 22.13：pnpm 11 依赖 node:sqlite 内置模块，node:20 下会 ERR_UNKNOWN_BUILTIN_MODULE。
# 仅影响构建阶段，运行阶段是 nginx:alpine，最终镜像里只有 dist/。
FROM node:22 AS build
WORKDIR /app

# 前端调用后端的基址；默认走相对路径 /api，由同源 nginx 反代到 backend:8000
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=${VITE_API_BASE}

# 包管理器：全仓库统一用 pnpm，锁文件为 pnpm-lock.yaml。
# 注意：历史遗留的 package-lock.json 已移入 _attic/，请勿再生成；
# 混用 npm ci 会绕开 pnpm 锁文件，导致镜像内依赖版本与本地漂移。
# 如果重新出现 package-lock.json，说明有人在用 npm 安装，应先删掉再提交。
#
# registry 默认走国内镜像：实测容器内直连 registry.npmjs.org 约三次挂一次
# （ERR_SSL_SSLV3_ALERT_BAD_RECORD_MAC），一次完整安装几百个请求几乎必然中断。
# 网络通畅的环境（如境外 CI）可覆盖回官方源：
#     docker build --build-arg NPM_REGISTRY=https://registry.npmjs.org ...
ARG NPM_REGISTRY=https://registry.npmmirror.com
# corepack 拉取 pnpm 本体走同一个源
ENV COREPACK_NPM_REGISTRY=${NPM_REGISTRY}
RUN corepack enable && corepack prepare pnpm@11.8.0 --activate

# 先装依赖（利用层缓存）。
# pnpm-workspace.yaml 必须一并拷入：它声明了 allowBuilds（esbuild、vue-demi），
# 缺了它 pnpm 会跳过这两个包的构建脚本，后面 vite build 会因 esbuild 未编译而失败。
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm config set registry ${NPM_REGISTRY} \
    && pnpm install --frozen-lockfile

# 再拷贝源码并构建（Vite 默认输出到 dist/）
# 宿主 node_modules 由根 .dockerignore 排除，不会覆盖上面装好的依赖
COPY frontend/ ./
RUN pnpm run build

# ---------- 运行阶段：nginx:alpine 托管 dist 并反代 /api ----------
FROM nginx:alpine

# 反代配置：/api 与 /api/ws（WebSocket 升级）转发到 backend:8000
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf

# 静态产物
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
