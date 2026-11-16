# NodeXProtocol Edge Node (`nodex-node` v1.0)

专为跑有 `3x-ui` 的家宽 / 动态 IP VPS 设计的独立容器化共享节点端。

## 核心特性
- **零冲突隔离**：独立容器、独立端口（默认 `24443`），限速做在容器内网卡 `eth0`，完全不影响宿主机 `3x-ui` 的自用带宽与端口。
- **仅 IP 变动才上报**：每 3 分钟（`IP_CHECK_INTERVAL_SEC=180`）在本地检测公网 IP，**IP 不变则零请求**，仅在 IP 变更或手动同步时上报 `api.nodexprotocol.com`。
- **容器内限速与月流量熔断**：支持 `.env` 与控制面 `/admin` 前台调速；月流量达标自动停服保护家宽。
- **安全沙箱与零日志**：屏蔽所有内网私有网段（无法访问宿主机 `3x-ui` 面板或局域网），拦截 BT/SMTP，禁用访问日志。

## 一键部署
上传本目录到 VPS（如 `/opt/nodex-node`）或推送到 GitHub 后执行：
```bash
chmod +x install.sh nodex && ./install.sh
```
部署完成后，随时在终端输入 **`nodex`** 即可打开交互式命令行管理后台。
