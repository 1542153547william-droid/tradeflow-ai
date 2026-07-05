# Cloudflare Worker：Anthropic 海外中转

给**大陆服务器**用的免费海外中转。杭州 ECS 连不上 `api.anthropic.com`，
让它把请求发到这个 Worker，Worker 从 Cloudflare 海外节点转发到 Anthropic。

## 一、部署 Worker（在你 Mac 上操作，约 3 分钟）

1. 注册/登录 Cloudflare（免费）：https://dash.cloudflare.com
2. 左侧 **Workers & Pages → Create → Create Worker**
3. 起个名字（如 `anthropic-relay`）→ **Deploy**（先部署个默认的）
4. 点 **Edit code**，把 [`anthropic-relay.js`](anthropic-relay.js) 的内容整段粘进去覆盖 → **Deploy**
5. 记下分配的地址：`https://anthropic-relay.<你的子域>.workers.dev`

（可选加固）在 Worker 的 **Settings → Variables** 加一个变量 `ACCESS_TOKEN`，
值自己定；之后调用要带 `x-relay-token` 头，防止别人白嫖你的 Worker。
> 注：本项目当前 provider 还没传这个头，先别设 ACCESS_TOKEN，需要时告诉我加上。

## 二、关键：从杭州服务器测试是否可达

`*.workers.dev` 有时会被墙从大陆访问。**必须在 ECS 上实测**：

```bash
curl -sS -m 15 https://anthropic-relay.<你的子域>.workers.dev/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" | head
```

- 返回一段 JSON（模型列表或鉴权信息）→ ✅ 通了，进第三步。
- 超时/连不上 → ❌ workers.dev 被墙，走下面「绑定自有域名」。

### 若 workers.dev 不通：绑自有域名（不需要 ICP 备案）

1. 买个便宜域名（阿里云/Namecheap 均可，约 ¥10–70/年）。
2. 把域名的 **Nameserver 改到 Cloudflare**（Cloudflare 添加站点时会给你两个 NS）。
3. Worker → **Settings → Domains & Routes → Add → Custom Domain**，
   绑一个子域如 `relay.你的域名.com`。
4. 用 `https://relay.你的域名.com` 重新做上面的 curl 测试。
> 纯做 Worker 中转、不指向大陆服务器，不触发 ICP 备案要求。

## 三、填到服务器 .env

测通后，在 ECS 的 `/opt/tradeflow-ai/.env` 里设：

```
TRADEFLOW_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxx
ANTHROPIC_BASE_URL=https://anthropic-relay.<你的子域>.workers.dev
```

然后 `docker compose up -d --build` 重启即可。验证：

```bash
curl -sS -X POST http://localhost/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"用一句话介绍你自己"}'
```
返回真实回答（不是 mock）就成了。
