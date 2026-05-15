# Caddy + Docker + 子域名 + HTTPS 配置总结

> 记录时间：2026-05-16 凌晨
> 域名：`1597133.xyz`（未备案）

---

## 一、背景与目标

使用 Caddy 作为统一反向代理网关，将 Docker 中的多个服务通过子域名暴露，实现：

- ✅ 统一域名访问（`1597133.xyz` → OpenClaw，`adminer.1597133.xyz` → Adminer）
- ✅ HTTPS 自动化
- ✅ 内网 Docker 服务通过反向代理安全暴露
- ✅ 子域名可随意扩展

---

## 二、整体架构

```
                    互联网
                      │
              ┌───────┴───────┐
              │  Caddy (HTTPS) │  ← 统一入口，443端口
              └───────┬───────┘
                      │
            ┌─────────┼─────────┐
            │         │         │
       OpenClaw   Adminer    MySQL
      (公网证书)  (内部CA)  (不暴露)
            │         │         │
            └─────────┼─────────┘
                      │
              net_openclaw (Docker 内部网络)
```

### 服务与端口

| 服务 | Docker 容器名 | 内部端口 | 访问地址 | 证书策略 |
|------|-------------|---------|---------|---------|
| Caddy | `caddy` | 80, 443 | — | — |
| OpenClaw | `openclaw` | 18789 | `1597133.xyz` | Let's Encrypt |
| Adminer | `adminer` | 8080 | `adminer.1597133.xyz` | Caddy Internal CA |
| MySQL | `mysql` | 3306 | 不对外暴露 | — |

---

## 三、核心问题链路（踩坑全记录）

### 问题 1：子域名无法访问，TLS handshake 失败

**现象：**
- `adminer.1597133.xyz` 无法访问
- `curl https://adminer.1597133.xyz` 返回 `TLS alert internal error`
- 但 `1597133.xyz`（OpenClaw）正常

**初步排查：**
- DNS A 记录正确指向服务器 IP ✅
- 443 端口正常 ✅
- Docker 网络正常 ✅

**根因：** HTTP-01 / TLS-ALPN 证书验证在国内网络环境下被拦截，adminer 子域名未成功签发 Let's Encrypt 证书。

---

### 问题 2：Let's Encrypt Rate Limit

**现象：** 多次重启 Caddy 试图重新签发证书，最终触发限流：

```
too many failed authorizations (rateLimited)
```

**教训：** ACME rate limit 是「时间锁」——触发后只能等，无法通过改配置绕过。**不要反复重启 Caddy 来试证书。**

---

### 问题 3：Docker 网络 DNS 断裂（⚠️ 核心坑）

**现象：**

```
lookup adminer on 127.0.0.53:53: server misbehaving
dial tcp 127.0.0.1:8080: connection refused
```

**根因分析：**

| 错误写法 | 问题 |
|---------|------|
| `reverse_proxy 127.0.0.1:8080` | 容器端口未映射到 host |
| `reverse_proxy localhost:8080` | Caddy 容器内 localhost 不等于宿主机 |
| `reverse_proxy adminer:8080` | Caddy 不在同一 Docker 网络中 |

**结论：** 所有服务（Caddy、OpenClaw、Adminer、MySQL）**必须加入同一个 Docker 网络**（`net_openclaw`）。Caddy 才能通过容器名（service name）做 DNS 解析。

---

### 问题 4：DNS-01 尝试失败

**尝试：** 使用 DNSPod DNS-01 验证绕过 HTTP 验证

**失败原因：**
- 误用 `caddy:builder` 镜像（builder 不是运行镜像）
- 未使用 `xcaddy` 编译 DNS 插件（报错 `module not registered`）
- 混淆了 A 记录和 NS 切换的概念

**最终未采用** DNSPod 方案，转而使用 Cloudflare DNS-01 + Caddy Internal CA 分层策略。

---

### 问题 5：Docker Compose 改动不生效

**现象：** 修改 `docker-compose.yml` 后 Caddy 仍然报网络错误

**原因：** `docker-compose up -d` 不会重建已有容器。需要：

```bash
docker-compose down && docker-compose up -d
```

---

## 四、最终解决方案

### 1. 统一 Docker 网络

所有服务加入 `net_openclaw`：

```yaml
# docker-compose.yml 关键片段
networks:
  net_openclaw:
    driver: bridge

services:
  caddy:
    networks:
      - net_openclaw

  openclaw:
    networks:
      - net_openclaw

  adminer:
    networks:
      - net_openclaw

  mysql:
    networks:
      - net_openclaw
```

### 2. Caddy 正确配置

```
# Caddyfile
1597133.xyz {
    reverse_proxy openclaw:18789
}

adminer.1597133.xyz {
    reverse_proxy adminer:8080
    tls internal
}
```

### 3. 证书策略分层

| 服务类型 | 证书方案 | 原因 |
|---------|---------|------|
| 公网服务（OpenClaw） | Let's Encrypt | 需要浏览器信任 |
| 内网工具（Adminer） | `tls internal` | 自己用，Caddy 内置 CA 足够，不消耗 LE 配额 |
| 数据库（MySQL） | 不暴露 | 仅 Docker 内部访问 |

---

## 五、关键经验总结

| # | 经验 | 一句话 |
|---|------|--------|
| 1 | **Docker 网络是命根子** | Caddy 通过容器名解析 DNS，不在同一网络 = 找不到服务 |
| 2 | **`127.0.0.1:8080` ≠ 容器服务** | 容器端口没映射到 host 时，localhost 访问不到 |
| 3 | **ACME rate limit 是时间锁** | 触发后只能等，不要反复重启试探 |
| 4 | **`tls internal` 是内网最佳方案** | 不消耗 LE 配额，自动续期，内网工具够用 |
| 5 | **修改 compose 文件必须 down+up** | `docker-compose up -d` 不会重建已有容器 |
| 6 | **国内 HTTP 验证容易被拦截** | 没有备案的域名，HTTP-01 基本不可靠 |
| 7 | **DNS-01 需要编译插件** | 原生 Caddy 镜像不带 DNS 插件，需要 xcaddy 构建 |

### 一句话总结

> 本次问题核心不是 HTTPS，而是 **Docker 网络 + Caddy DNS + ACME 重试叠加** 导致的链路断裂。

---

## 六、当前状态说明

> ⚠️ 目前子域名使用的是 Caddy 自签发证书（`tls internal`），浏览器访问会提示「不安全」。
> 
> **对个人开发和学习来说完全不影响使用。** 等域名备案完成后，可以直接切换为 Let's Encrypt 公信证书，浏览器就不会报警了。

---

## 七、附录：参考命令

```bash
# 重建所有容器（网络变更后必须执行）
docker-compose down && docker-compose up -d

# 查看 Caddy 日志
docker logs caddy

# 测试容器间 DNS 解析
docker exec caddy nslookup adminer

# 测试端口连通性
docker exec caddy curl -k https://adminer:8080

# 查看 Docker 网络中的容器
docker network inspect net_openclaw
```
