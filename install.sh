#!/usr/bin/env bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

NODE_DIR="/opt/nodex-node"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}请使用 root 权限运行本脚本 (sudo -i)${NC}"
    exit 1
fi

echo -e "${CYAN}================================================${NC}"
echo -e "${CYAN}   NodeXProtocol Edge Node (nodex-node v1.0)    ${NC}"
echo -e "${CYAN}   独立容器隔离部署 · 不影响宿主机 3x-ui 服务   ${NC}"
echo -e "${CYAN}================================================${NC}"

# 1. 检测并安装 Docker（若未安装）
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${YELLOW}未检测到 Docker，正在安装 Docker...${NC}"
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

if ! docker compose version >/dev/null 2>&1; then
    echo -e "${YELLOW}正在安装 docker-compose 插件...${NC}"
    apt-get update -y && apt-get install -y docker-compose-plugin || true
fi

mkdir -p "$NODE_DIR"

# 2. 若通过 curl 远程执行且当前目录无项目文件，则从 GitHub 拉取
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ -f "$SCRIPT_DIR/agent.py" ]; then
    if [ "$SCRIPT_DIR" != "$NODE_DIR" ]; then
        cp -rf "$SCRIPT_DIR"/* "$NODE_DIR"/
    fi
else
    GITHUB_REPO="${GITHUB_REPO:-}"
    if [ -z "$GITHUB_REPO" ]; then
        read -rp "请输入你的 nodex-node GitHub 仓库地址 (如 https://github.com/user/nodex-node.git): " GITHUB_REPO
    fi
    if [ -d "$NODE_DIR/.git" ]; then
        cd "$NODE_DIR" && git pull --ff-only
    else
        rm -rf "$NODE_DIR"
        git clone "$GITHUB_REPO" "$NODE_DIR"
    fi
fi

cd "$NODE_DIR"

# 3. 交互式生成 .env（已存在则保留）
if [ ! -f "$NODE_DIR/.env" ]; then
    echo ""
    read -rp "请输入节点对外端口 [默认 24443，注意避开 3x-ui 端口]: " NODE_PORT
    NODE_PORT=${NODE_PORT:-24443}

    read -rp "请输入节点地区代码 (如 HK / US，留空自动识别): " NODE_COUNTRY
    read -rp "请输入节点名称备注 (如 HK-Res-01，留空自动生成): " NODE_TAG

    read -rp "请输入带宽上限 Mbps [默认 30，0=不限速]: " MAX_BW_MBPS
    MAX_BW_MBPS=${MAX_BW_MBPS:-30}

    read -rp "请输入月流量上限 GB [默认 500，0=不限制]: " MAX_MONTHLY_GB
    MAX_MONTHLY_GB=${MAX_MONTHLY_GB:-500}

    cat > "$NODE_DIR/.env" <<EOF
COORDINATOR_URL=https://api.nodexprotocol.com
NODE_PORT=${NODE_PORT}
NODE_COUNTRY=${NODE_COUNTRY}
NODE_TAG=${NODE_TAG}
MAX_BW_MBPS=${MAX_BW_MBPS}
MAX_MONTHLY_GB=${MAX_MONTHLY_GB}
IP_CHECK_INTERVAL_SEC=180
REALITY_SNI=gateway.icloud.com
EOF
    echo -e "${GREEN}已生成配置文件 $NODE_DIR/.env${NC}"
else
    echo -e "${GREEN}检测到已有配置文件 .env，自动保留原配置${NC}"
fi

# 4. 放行端口（若启用了 ufw）
source "$NODE_DIR/.env"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow "${NODE_PORT:-24443}/tcp" >/dev/null 2>&1 || true
    echo -e "${GREEN}已自动在 UFW 放行端口 ${NODE_PORT:-24443}/tcp${NC}"
fi

# 5. 安装快捷管理命令 nodex
cp -f "$NODE_DIR/nodex" /usr/local/bin/nodex
chmod +x /usr/local/bin/nodex

# 6. 构建并启动容器
echo -e "${CYAN}正在构建并启动 nodex-node 容器...${NC}"
docker compose up -d --build

echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN} 部署完成！以后随时输入命令: nodex 即可打开管理菜单 ${NC}"
echo -e "${GREEN} 常用命令: nodex | nodex status | nodex logs     ${NC}"
echo -e "${GREEN}================================================${NC}"
