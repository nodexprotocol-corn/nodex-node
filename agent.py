import json
import os
import random
import secrets
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
import httpx

DATA_DIR = Path("/app/data")
IDENTITY_FILE = DATA_DIR / "identity.json"
TRAFFIC_FILE = DATA_DIR / "traffic.json"
SINGBOX_CFG = DATA_DIR / "sing-box.json"
FORCE_SYNC_FLAG = DATA_DIR / ".force_sync"
ENV_FILE = Path("/app/.env")

# P2-09: 非大厂高信誉 TLS 1.3 + H2 随机伪装域名池 (避开苹果/谷歌/微软等高频特征大厂)
SAFE_REALITY_SNI_POOL = [
    "www.amd.com",
    "www.nvidia.com",
    "www.qualcomm.com",
    "www.cisco.com",
    "www.logitech.com",
    "www.corsair.com",
    "www.asus.com",
    "www.msi.com",
    "www.synology.com",
    "www.seagate.com",
    "www.westerndigital.com",
    "www.ieee.org",
]


def pick_reachable_sni(exclude_sni: str = "") -> str:
    candidates = [s for s in SAFE_REALITY_SNI_POOL if s != exclude_sni]
    random.shuffle(candidates)
    for host in candidates:
        try:
            with socket.create_connection((host, 443), timeout=2.5):
                return host
        except Exception:
            continue
    return random.choice(SAFE_REALITY_SNI_POOL)


def resolve_active_sni(cfg: dict, ident: dict, force_rotate: bool = False) -> tuple[str, bool]:
    configured = cfg.get("REALITY_SNI", "auto").strip()
    # 将旧版默认 gateway.icloud.com 自动纳入动态随机池
    use_auto_pool = configured.lower() in ("", "auto", "gateway.icloud.com", "www.intel.com")
    if not use_auto_pool:
        changed = ident.get("current_sni") != configured
        ident["current_sni"] = configured
        return configured, changed

    now_ts = int(time.time())
    cur_sni = ident.get("current_sni", "")
    last_rot = int(ident.get("last_sni_rotated_at", 0) or 0)
    rotate_sec = max(1, int(cfg.get("SNI_ROTATE_HOURS", 24))) * 3600

    if force_rotate or not cur_sni or cur_sni not in SAFE_REALITY_SNI_POOL or (now_ts - last_rot) >= rotate_sec:
        new_sni = pick_reachable_sni(exclude_sni=cur_sni)
        ident["current_sni"] = new_sni
        ident["last_sni_rotated_at"] = now_ts
        return new_sni, True

    return cur_sni, False


def load_env_settings() -> dict:
    cfg = {
        "COORDINATOR_URL": os.environ.get("COORDINATOR_URL", "https://api.nodexprotocol.com").rstrip("/"),
        "NODE_PORT": int(os.environ.get("NODE_PORT", "24443")),
        "NODE_COUNTRY": os.environ.get("NODE_COUNTRY", "").strip().upper(),
        "NODE_TAG": os.environ.get("NODE_TAG", "").strip(),
        "MAX_BW_MBPS": int(os.environ.get("MAX_BW_MBPS", "30")),
        "MAX_MONTHLY_GB": int(os.environ.get("MAX_MONTHLY_GB", "500")),
        "IP_CHECK_INTERVAL_SEC": int(os.environ.get("IP_CHECK_INTERVAL_SEC", "180")),
        "REALITY_SNI": os.environ.get("REALITY_SNI", "auto").strip(),
        "SNI_ROTATE_HOURS": int(os.environ.get("SNI_ROTATE_HOURS", "24")),
    }
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k in ("NODE_PORT", "MAX_BW_MBPS", "MAX_MONTHLY_GB", "IP_CHECK_INTERVAL_SEC", "SNI_ROTATE_HOURS"):
                try:
                    cfg[k] = int(v)
                except ValueError:
                    pass
            elif k in cfg:
                cfg[k] = v.upper() if k == "NODE_COUNTRY" else v.rstrip("/") if k == "COORDINATOR_URL" else v
    return cfg


def generate_reality_keypair() -> tuple[str, str]:
    out = subprocess.check_output(["sing-box", "generate", "reality-keypair"], text=True)
    priv, pub = "", ""
    for line in out.splitlines():
        if line.startswith("PrivateKey:"):
            priv = line.split(":", 1)[1].strip()
        elif line.startswith("PublicKey:"):
            pub = line.split(":", 1)[1].strip()
    if not priv or not pub:
        raise RuntimeError(f"无法生成 REALITY 密钥对: {out}")
    return priv, pub


def load_or_create_identity() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if IDENTITY_FILE.exists():
        return json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
    priv, pub = generate_reality_keypair()
    initial_sni = pick_reachable_sni()
    ident = {
        "node_uid": f"node-{secrets.token_hex(8)}",
        "node_secret": secrets.token_hex(24),
        "uuid": str(uuid.uuid4()),
        "reality_private_key": priv,
        "reality_public_key": pub,
        "reality_short_id": secrets.token_hex(4),
        "last_public_ip": "",
        "current_sni": initial_sni,
        "last_sni_rotated_at": int(time.time()),
    }
    IDENTITY_FILE.write_text(json.dumps(ident, indent=2), encoding="utf-8")
    return ident


def save_identity(ident: dict):
    IDENTITY_FILE.write_text(json.dumps(ident, indent=2), encoding="utf-8")


def get_public_ip() -> str:
    urls = [
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
        "https://icanhazip.com",
    ]
    for url in urls:
        try:
            r = httpx.get(url, timeout=6.0)
            if r.status_code == 200:
                ip = r.text.strip()
                if ip and len(ip) <= 45 and "." in ip:
                    return ip
        except Exception:
            continue
    return ""


def write_singbox_config(ident: dict, port: int, sni: str):
    cfg = {
        "log": {"level": "error", "disabled": False},
        "inbounds": [
            {
                "type": "vless",
                "tag": "vless-in",
                "listen": "0.0.0.0",
                "listen_port": port,
                "users": [
                    {
                        "uuid": ident["uuid"],
                        "flow": "xtls-rprx-vision",
                    }
                ],
                "tls": {
                    "enabled": True,
                    "server_name": sni,
                    "reality": {
                        "enabled": True,
                        "handshake": {"server": sni, "server_port": 443},
                        "private_key": ident["reality_private_key"],
                        "short_id": [ident["reality_short_id"]],
                    },
                },
            }
        ],
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": [
                {"ip_is_private": True, "outbound": "block"},
                {"port": [25, 465, 587], "outbound": "block"},
                {"protocol": ["bittorrent"], "outbound": "block"},
            ],
            "final": "direct",
        },
    }
    SINGBOX_CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def apply_tc_limit(mbps: int):
    try:
        subprocess.run(["tc", "qdisc", "del", "dev", "eth0", "root"], stderr=subprocess.DEVNULL, check=False)
        if mbps > 0:
            subprocess.run(
                ["tc", "qdisc", "replace", "dev", "eth0", "root", "tbf",
                 "rate", f"{mbps}mbit", "burst", "256kbit", "latency", "50ms"],
                check=True,
            )
            print(f"[TC] 容器内出口带宽已限制为 {mbps} Mbps", flush=True)
        else:
            print("[TC] 当前为不限速模式", flush=True)
    except Exception as e:
        print(f"[TC] 限速应用失败 (请确认已授予 NET_ADMIN 权限): {e}", flush=True)


def read_eth0_bytes() -> int:
    try:
        rx = int(Path("/sys/class/net/eth0/statistics/rx_bytes").read_text().strip())
        tx = int(Path("/sys/class/net/eth0/statistics/tx_bytes").read_text().strip())
        return rx + tx
    except Exception:
        return 0


def update_monthly_traffic(last_raw: int) -> tuple[int, float]:
    month = datetime.utcnow().strftime("%Y-%m")
    state = {"month": month, "used_bytes": 0}
    if TRAFFIC_FILE.exists():
        try:
            loaded = json.loads(TRAFFIC_FILE.read_text(encoding="utf-8"))
            if loaded.get("month") == month:
                state = loaded
        except Exception:
            pass
    cur_raw = read_eth0_bytes()
    if last_raw > 0 and cur_raw >= last_raw:
        state["used_bytes"] += (cur_raw - last_raw)
    TRAFFIC_FILE.write_text(json.dumps(state), encoding="utf-8")
    return cur_raw, round(state["used_bytes"] / (1024 * 1024), 2)


def register_node(cfg: dict, ident: dict, public_ip: str, active_sni: str) -> dict | None:
    tag = cfg["NODE_TAG"] or f"Edge-{cfg['NODE_COUNTRY'] or 'Auto'}-{ident['node_uid'][-4:]}"
    payload = {
        "node_uid": ident["node_uid"],
        "node_secret": ident["node_secret"],
        "tag": tag,
        "protocol": "vless",
        "server": public_ip,
        "server_port": cfg["NODE_PORT"],
        "uuid": ident["uuid"],
        "flow": "xtls-rprx-vision",
        "security": "reality",
        "transport_type": "tcp",
        "sni": active_sni,
        "reality_pubkey": ident["reality_public_key"],
        "reality_short_id": ident["reality_short_id"],
        "fingerprint": "chrome",
        "country": cfg["NODE_COUNTRY"] or None,
        "max_bw_mbps": cfg["MAX_BW_MBPS"],
        "max_monthly_gb": cfg["MAX_MONTHLY_GB"],
    }
    try:
        r = httpx.post(f"{cfg['COORDINATOR_URL']}/api/v1/node/register", json=payload, timeout=15.0)
        if r.status_code == 200:
            data = r.json()
            print(f"[REG] 节点注册成功: {data.get('server')}:{cfg['NODE_PORT']} ({data.get('country_code')}, SNI={active_sni})", flush=True)
            return data
        print(f"[REG] 注册失败 HTTP {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"[REG] 注册异常: {e}", flush=True)
    return None


def report_heartbeat(cfg: dict, ident: dict, public_ip: str, used_mb: float, active_sni: str, is_online: bool = True) -> dict | None:
    payload = {
        "node_uid": ident["node_uid"],
        "node_secret": ident["node_secret"],
        "server": public_ip,
        "server_port": cfg["NODE_PORT"],
        "sni": active_sni,
        "used_monthly_mb": used_mb,
        "load_level": "green",
        "active_conns": 0,
        "is_online": is_online,
    }
    try:
        r = httpx.post(f"{cfg['COORDINATOR_URL']}/api/v1/node/heartbeat", json=payload, timeout=12.0)
        if r.status_code == 200:
            return r.json()
        print(f"[SYNC] 上报异常 HTTP {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"[SYNC] 上报失败: {e}", flush=True)
    return None


def main():
    cfg = load_env_settings()
    ident = load_or_create_identity()

    if "--status" in sys.argv:
        _, used_mb = update_monthly_traffic(0)
        active_sni, _ = resolve_active_sni(cfg, ident, force_rotate=False)
        print(json.dumps({
            "node_uid": ident["node_uid"],
            "public_ip": ident.get("last_public_ip", ""),
            "port": cfg["NODE_PORT"],
            "country": cfg["NODE_COUNTRY"] or "AUTO",
            "reality_sni": active_sni,
            "sni_rotate_hours": cfg["SNI_ROTATE_HOURS"],
            "max_bw_mbps": cfg["MAX_BW_MBPS"],
            "max_monthly_gb": cfg["MAX_MONTHLY_GB"],
            "used_monthly_mb": used_mb,
        }, ensure_ascii=False, indent=2))
        return

    if "--rotate-sni" in sys.argv:
        new_sni, _ = resolve_active_sni(cfg, ident, force_rotate=True)
        save_identity(ident)
        write_singbox_config(ident, cfg["NODE_PORT"], new_sni)
        ip = get_public_ip() or ident.get("last_public_ip", "")
        _, used_mb = update_monthly_traffic(0)
        res = register_node(cfg, ident, ip, new_sni)
        FORCE_SYNC_FLAG.touch()
        print(json.dumps({"rotated_sni": new_sni, "sync": res or "ok"}, ensure_ascii=False, indent=2))
        return

    if "--sync" in sys.argv:
        ip = get_public_ip() or ident.get("last_public_ip", "")
        active_sni, sni_changed = resolve_active_sni(cfg, ident, force_rotate=False)
        if sni_changed:
            save_identity(ident)
        _, used_mb = update_monthly_traffic(0)
        res = report_heartbeat(cfg, ident, ip, used_mb, active_sni, is_online=True)
        if res is None:
            res = register_node(cfg, ident, ip, active_sni)
        print(json.dumps(res or {"error": "sync failed"}, ensure_ascii=False))
        return

    public_ip = get_public_ip() or ident.get("last_public_ip", "")
    if not public_ip:
        print("[ERR] 无法获取公网 IP，10 秒后重试...", flush=True)
        time.sleep(10)
        public_ip = get_public_ip()
    if public_ip:
        ident["last_public_ip"] = public_ip

    active_sni, _ = resolve_active_sni(cfg, ident, force_rotate=False)
    save_identity(ident)

    write_singbox_config(ident, cfg["NODE_PORT"], active_sni)
    reg_res = register_node(cfg, ident, public_ip, active_sni)

    effective_bw = cfg["MAX_BW_MBPS"]
    effective_quota_gb = cfg["MAX_MONTHLY_GB"]
    is_paused = False
    if reg_res:
        if reg_res.get("max_bw_mbps", 0) > 0:
            effective_bw = reg_res["max_bw_mbps"]
        if reg_res.get("max_monthly_gb", 0) > 0:
            effective_quota_gb = reg_res["max_monthly_gb"]
        is_paused = bool(reg_res.get("is_paused", False))

    apply_tc_limit(effective_bw)
    sb_proc = None
    if not is_paused:
        sb_proc = subprocess.Popen(["sing-box", "run", "-c", str(SINGBOX_CFG)])
        print(f"[CORE] sing-box 已启动 (PID={sb_proc.pid}, 端口={cfg['NODE_PORT']}, SNI={active_sni})", flush=True)
    else:
        print("[CORE] 节点当前处于暂停状态，暂不启动代理监听", flush=True)

    running = True

    def handle_exit(signum, frame):
        nonlocal running
        running = False
        print("[SYS] 收到退出信号，正在通知控制面下线...", flush=True)
        try:
            httpx.post(
                f"{cfg['COORDINATOR_URL']}/api/v1/node/offline",
                json={"node_uid": ident["node_uid"], "node_secret": ident["node_secret"]},
                timeout=5.0,
            )
        except Exception:
            pass
        if sb_proc and sb_proc.poll() is None:
            sb_proc.terminate()
            sb_proc.wait(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    last_raw_bytes = read_eth0_bytes()
    last_bw = effective_bw

    while running:
        time.sleep(cfg["IP_CHECK_INTERVAL_SEC"])
        cfg = load_env_settings()
        ident = load_or_create_identity()
        last_raw_bytes, used_mb = update_monthly_traffic(last_raw_bytes)
        cur_ip = get_public_ip()
        force_sync = FORCE_SYNC_FLAG.exists()
        if force_sync:
            FORCE_SYNC_FLAG.unlink(missing_ok=True)

        # 检查是否到达 SNI 自动轮换周期
        active_sni, sni_rotated = resolve_active_sni(cfg, ident, force_rotate=False)
        if sni_rotated:
            print(f"[SNI] 触发非大厂随机 SNI 轮换 -> {active_sni}", flush=True)
            save_identity(ident)
            write_singbox_config(ident, cfg["NODE_PORT"], active_sni)
            if sb_proc and sb_proc.poll() is None:
                sb_proc.terminate()
                try:
                    sb_proc.wait(timeout=4)
                except Exception:
                    pass
                sb_proc = subprocess.Popen(["sing-box", "run", "-c", str(SINGBOX_CFG)])

        # 检查是否触发月流量熔断
        quota_exceeded = effective_quota_gb > 0 and (used_mb / 1024.0) >= effective_quota_gb
        if quota_exceeded and sb_proc and sb_proc.poll() is None:
            print(f"[QUOTA] 已达月流量上限 {effective_quota_gb} GB，自动熔断停服！", flush=True)
            sb_proc.terminate()
            sb_proc = None
            report_heartbeat(cfg, ident, cur_ip or ident["last_public_ip"], used_mb, active_sni, is_online=False)
            continue

        # 仅当公网 IP 变动、SNI 轮换或手动触发同步时才向控制面上报
        ip_changed = bool(cur_ip and cur_ip != ident.get("last_public_ip", ""))
        if ip_changed or sni_rotated or force_sync:
            if ip_changed:
                print(f"[IP] 检测到公网 IP 变动: {ident.get('last_public_ip')} -> {cur_ip}，正在定标上报...", flush=True)
                ident["last_public_ip"] = cur_ip
                save_identity(ident)
            res = report_heartbeat(cfg, ident, cur_ip or ident["last_public_ip"], used_mb, active_sni, is_online=not quota_exceeded)
            if res:
                remote_bw = res.get("max_bw_mbps", 0)
                new_bw = remote_bw if remote_bw > 0 else cfg["MAX_BW_MBPS"]
                if new_bw != last_bw:
                    apply_tc_limit(new_bw)
                    last_bw = new_bw
                if res.get("max_monthly_gb", 0) > 0:
                    effective_quota_gb = res["max_monthly_gb"]
                is_paused = bool(res.get("is_paused", False))
                if is_paused and sb_proc and sb_proc.poll() is None:
                    sb_proc.terminate()
                    sb_proc = None
                elif not is_paused and not quota_exceeded and (sb_proc is None or sb_proc.poll() is not None):
                    sb_proc = subprocess.Popen(["sing-box", "run", "-c", str(SINGBOX_CFG)])
        else:
            if cfg["MAX_BW_MBPS"] != last_bw:
                apply_tc_limit(cfg["MAX_BW_MBPS"])
                last_bw = cfg["MAX_BW_MBPS"]


if __name__ == "__main__":
    main()
