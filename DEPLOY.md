# 部署到阿里云 ECS（Docker + 公网 IP + HTTP）

目标：把 `tradeflow-ai` 跑成一个公网可访问的聊天页面。
前提：ECS 已开好（香港地域推荐），安全组已放行 **22 / 80 / 443**，本机能 SSH 上去。

> 现在先用 `http://公网IP` 跑通，没有域名/HTTPS。等有域名了再加 Nginx + certbot。

---

## 1. 连上服务器

```bash
ssh root@<你的公网IP>
```

## 2. 确认 Docker 可用

买实例时勾了「Docker 社区版」，一般已装好：

```bash
docker --version
docker compose version
```

若没有 `docker compose`（老版本），装 compose 插件：

```bash
apt-get update && apt-get install -y docker-compose-plugin
```

## 3. 让服务器能拉取私有仓库（Deploy Key）

在**服务器上**生成一把只读部署密钥：

```bash
ssh-keygen -t ed25519 -C "ecs-deploy" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

把打印出来的公钥，加到 GitHub 仓库：
**仓库 → Settings → Deploy keys → Add deploy key**（不用勾 Allow write）。

验证：

```bash
ssh -T git@github.com   # 看到 "Hi BuddyDing/..." 即成功
```

> 香港地域直连 github.com:22 正常。若你的地域连不上 22，把下面 clone 改成 HTTPS：
> `git clone https://<用户名>:<PAT>@github.com/BuddyDing/tradeflow-ai.git`

## 4. 拉代码

```bash
cd /opt
git clone -b feat/harness-scaffold git@github.com:BuddyDing/tradeflow-ai.git
cd tradeflow-ai
```

## 5. 配置环境变量

```bash
cp .env.example .env
vi .env
```

- 只想先跑通页面 → 保持 `TRADEFLOW_PROVIDER=mock`（回答是假数据，但流程能通）。
- 要真实回答 → 设：
  ```
  TRADEFLOW_PROVIDER=anthropic
  ANTHROPIC_API_KEY=sk-ant-xxxxx
  ```

## 6. 构建并启动

```bash
docker compose up -d --build
docker compose logs -f          # 看启动日志，Ctrl+C 退出（不影响运行）
```

## 7. 打开页面

浏览器访问：`http://<你的公网IP>/`

自检：

```bash
curl http://localhost/healthz            # {"ok":true}
curl http://localhost/api/info           # 当前 provider/model
```

---

## 常用运维

```bash
docker compose ps                # 状态
docker compose logs -f web       # 日志
docker compose restart           # 重启
docker compose down              # 停止并删容器
```

## 更新代码后重新部署

```bash
cd /opt/tradeflow-ai
git pull
docker compose up -d --build
```

## 安全收尾（强烈建议）

1. **安全组**：把 22 端口来源改成只允许你自己的 IP（阿里云控制台 → 安全组 → 入方向）。
2. **SSH 只留密钥**：编辑 `/etc/ssh/sshd_config`，设 `PasswordAuthentication no`，然后 `systemctl restart sshd`。
3. 定期 `apt-get update && apt-get upgrade`。

## 下一步（等有域名时上 HTTPS）

1. 域名解析 A 记录 → 公网 IP。
2. 在 compose 里加一个 Nginx 服务反代到 `web:8000`，用 certbot 签 Let's Encrypt 证书。
3. 需要时我再给你完整的 Nginx + HTTPS compose 配置。
