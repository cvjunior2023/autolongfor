#!/bin/bash
# ============================================================
# 龙湖天街自动化签到 - 服务器一键部署脚本
# ============================================================
set -e

BASE=/data/autolongfor
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
step() { echo; echo -e "${YELLOW}====== $1 ======${NC}"; }

if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[✗]${NC} 请以 root 执行：sudo bash deploy.sh"
  exit 1
fi

step "1/7  检查并安装 Docker"
if command -v docker &>/dev/null; then
  info "Docker 已安装：$(docker --version)"
else
  warn "正在安装 Docker..."
  curl -fsSL https://get.docker.com | bash
  systemctl enable --now docker
  info "Docker 安装完成：$(docker --version)"
fi

step "2/7  配置 Docker 镜像加速"
DAEMON=/etc/docker/daemon.json
if [ -f "$DAEMON" ] && grep -q "registry-mirrors" "$DAEMON"; then
  info "镜像加速器已配置，跳过"
else
  warn "配置镜像加速器..."
  mkdir -p /etc/docker
  cat > "$DAEMON" <<'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://docker.nju.edu.cn"
  ]
}
EOF
  systemctl daemon-reexec 2>/dev/null || true
  systemctl restart docker
  info "镜像加速器已配置，Docker 已重启"
fi

step "3/7  创建目录结构"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ "$SCRIPT_DIR" != "$BASE" ]; then
  warn "部署到 $BASE ..."
  mkdir -p "$BASE" "$BASE/data"
  cp -r "$SCRIPT_DIR"/* "$BASE/" 2>/dev/null || true
  cd "$BASE"
fi
mkdir -p "$BASE/data"
info "目录已就绪：$BASE"

step "4/7  配置账户信息"
CONFIG_FILE="$BASE/lhtj_data.json"
if grep -q "138xxxxxxxx" "$CONFIG_FILE" 2>/dev/null; then
  echo ""
  warn "请编辑配置文件，填入真实账户信息："
  echo ""
  echo "  vi $CONFIG_FILE"
  echo ""
  echo "编辑完成后按回车继续..."
  read -r
else
  info "lhtj_data.json 已配置"
fi

step "5/7  拉取 Docker 镜像"
echo "拉取镜像（从阿里云 ACR）..."
docker compose -f "$BASE/docker-compose.yml" pull
info "镜像拉取完成"

step "6/7  测试运行"
echo "执行一次签到测试..."
docker compose -f "$BASE/docker-compose.yml" up --abort-on-container-exit
info "测试完成！请检查上方日志。"

step "7/7  配置定时任务（cron）"
CRON_ENTRIES="# 龙湖天街自动签到
0 10 * * * cd /data/autolongfor && docker compose up > /dev/null 2>&1
0 14 * * * cd /data/autolongfor && docker compose up > /dev/null 2>&1
0 19 * * * cd /data/autolongfor && docker compose up > /dev/null 2>&1"

if crontab -l 2>/dev/null | grep -q "autolongfor"; then
  info "定时任务已存在，跳过"
else
  (crontab -l 2>/dev/null; echo "$CRON_ENTRIES") | crontab -
  info "定时任务已添加（每天 10:00 / 14:00 / 19:00 北京时间）"
  crontab -l | grep autolongfor
fi

echo ""
echo -e "${GREEN}============================================"
echo "  部署完成！"
echo -e "============================================${NC}"
echo ""
echo "  📂 工作目录：$BASE"
echo "  📄 配置文件：$BASE/lhtj_data.json"
echo "  🗄️  数据目录：$BASE/data/"
echo ""
echo "  ▶️  手动运行：docker compose -f $BASE/docker-compose.yml up"
echo "  🔍 查看日志：docker compose -f $BASE/docker-compose.yml logs"
echo "  ⏰ 定时：每天 10:00 / 14:00 / 19:00（北京时间）"
echo ""
