# NodeXProtocol Edge Node (`nodex-node`)

NodeXProtocol 网络的轻量级边缘节点程序，支持 Docker 容器隔离运行，不干扰宿主机已有服务，并支持自定义带宽限速、月流量上限保护及命令行一键管理。

## 一键部署（从 GitHub 拉取）

> 要求：Linux 系统（Ubuntu / Debian 等），具备 `root` 权限。若未安装 Docker，脚本会自动安装。

### 方式一：一条命令安装（推荐）

```
GITHUB_REPO="https://github.com/nodexprotocol-corn/nodex-node.git" bash <(curl -fsSL https://raw.githubusercontent.com/nodexprotocol-corn/nodex-node/main/install.sh)

```

### 方式二：克隆后安装

```
git clone https://github.com/nodexprotocol-corn/nodex-node.git /opt/nodex-node
cd /opt/nodex-node && chmod +x install.sh nodex && ./install.sh

```

运行后按提示输入以下信息即可完成部署：

* **对外端口**（默认 `24443`）

* **地区代码**（如 `HK`、`US`，留空自动识别）

* **节点备注名**（留空自动生成）

* **带宽上限（Mbps）**与**月流量上限（GB）**

## 常用管理命令

部署完成后，在终端输入 **`nodex`** 即可打开交互式管理菜单：

* 启动 / 停止 / 重启节点

* 随时修改带宽限速与月流量上限

* 查看当前运行状态与已用流量

* 查看运行日志

* 一键从 GitHub 更新（自动保留本地配置）

* 彻底卸载节点