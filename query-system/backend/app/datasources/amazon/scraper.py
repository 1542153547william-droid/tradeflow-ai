"""Playwright 浏览器爬虫数据源（回退通道，分层结构）。

⚠️ 合规：Amazon 服务条款限制自动化抓取。此通道仅用于本地开发/低频回退，
内置随机延时、UA 轮换、并发上限、反自动化指纹；遇验证码/拦截时抛 DataSourceError。

产出对齐 rawdata.md §5.1 的分层 Product：
  search_top_products → search_context / base_info / pricing（列表页）
  fetch_detail        → base_info(BSR/品牌/父体) / logistics / content（详情页）
  fetch_reviews       → reviews_sample（评论页）
  fetch_qa            → qa_sample（问答，多数已下线）

生产环境请优先使用 ApiSource（合规第三方 API）。
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ...config import Settings
from ...models import (
    BaseInfo,
    Content,
    Coupon,
    Logistics,
    Pricing,
    Product,
    QA,
    RankNode,
    Review,
    SearchContext,
)
from ..base import DataSource, DataSourceError

logger = logging.getLogger(__name__)

# 调试用：抓取被拦/解析为空时自动截图，落到 backend/debug_shots/（已 gitignore）。
# 调好后想关掉把这里改成 False 即可。
_DEBUG_SHOTS = True
_SHOT_DIR = Path("debug_shots")

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]

# 站点 → 币种。价格数值单独解析，币种按站点判定，避免 $ 在多国站点的歧义。
_MARKET_CURRENCY = {
    "amazon.com": "USD", "amazon.co.uk": "GBP", "amazon.de": "EUR",
    "amazon.fr": "EUR", "amazon.es": "EUR", "amazon.it": "EUR",
    "amazon.nl": "EUR", "amazon.co.jp": "JPY", "amazon.ca": "CAD",
    "amazon.com.au": "AUD", "amazon.in": "INR", "amazon.com.mx": "MXN",
    "amazon.com.br": "BRL", "amazon.se": "SEK", "amazon.pl": "PLN",
}

# 注入脚本：抹掉无头浏览器最明显的自动化指纹（navigator.webdriver）。
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def _parse_money(text: str) -> Optional[float]:
    """从价格文本解析数值，兼容 `1,234.56`（美/英）与 `1.234,56`（德/法）两种格式。"""
    m = re.search(r"[\d.,]+", text)
    if not m:
        return None
    num = m.group()
    if "." in num and "," in num:
        # 同时出现时，最后一个分隔符是小数点
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")  # 1.234,56 → 1234.56
        else:
            num = num.replace(",", "")                    # 1,234.56 → 1234.56
    elif "," in num:
        # 仅逗号：形如 19,99 视为小数点；1,234 视为千分位
        if re.fullmatch(r"\d{1,3}(,\d{3})+", num):
            num = num.replace(",", "")
        else:
            num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def _clean_brand(text: str) -> Optional[str]:
    """把 byline 文案规整成品牌名：`Visit the Anker Store` / `Brand: Anker` → `Anker`。"""
    t = " ".join(text.split())
    t = re.sub(r"^(?:Visit the|Brand:|Store:|ブランド:)\s*", "", t, flags=re.I)
    t = re.sub(r"(?:'s)?\s+Store$|\s*ストア$", "", t, flags=re.I)
    t = t.strip()
    return t if 0 < len(t) <= 40 else None


def _parse_currency(text: str, fallback: str) -> str:
    """从价格文本判定币种。"""
    t = text.upper()
    for code in ("USD", "GBP", "EUR", "JPY", "CAD", "AUD", "INR", "MXN", "BRL", "SEK", "PLN"):
        if code in t:
            return code
    if "£" in text:
        return "GBP"
    if "€" in text:
        return "EUR"
    if "¥" in text:
        return "JPY" if fallback == "JPY" else "CNY"
    return fallback


def _parse_weight_lbs(text: str) -> Optional[float]:
    """把重量文本换算成磅：'1.2 pounds' → 1.2；'8 ounces' → 0.5；'500 g' → 1.1。"""
    m = re.search(r"([\d.]+)\s*(pounds?|lbs?|ounces?|oz|kilograms?|kg|grams?|g)\b", text, re.I)
    if not m:
        return None
    val, unit = float(m.group(1)), m.group(2).lower()
    if unit.startswith(("pound", "lb")):
        return round(val, 3)
    if unit.startswith(("ounce", "oz")):
        return round(val / 16.0, 3)
    if unit.startswith(("kilogram", "kg")):
        return round(val * 2.20462, 3)
    if unit.startswith(("gram", "g")):
        return round(val * 0.00220462, 3)
    return None


class ScraperSource(DataSource):
    name = "scraper"
    platform = "amazon"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._browser = None
        self._pw = None
        self._launch_lock = asyncio.Lock()

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        async with self._launch_lock:
            if self._browser is not None:
                return
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:  # pragma: no cover
                raise DataSourceError("Playwright 未安装，无法使用爬虫通道") from exc

            self._pw = await async_playwright().start()
            launch_kwargs = {
                "headless": self.settings.scraper_headless,
                # --no-sandbox / --disable-dev-shm-usage: 在 Docker 里以 root 跑
                # Chromium 必需（无沙箱权限、/dev/shm 偏小）。
                "args": ["--disable-blink-features=AutomationControlled",
                         "--no-sandbox", "--disable-dev-shm-usage"],
            }
            if self.settings.chromium_path:
                launch_kwargs["executable_path"] = self.settings.chromium_path
            try:
                self._browser = await self._pw.chromium.launch(**launch_kwargs)
            except Exception as exc:
                raise DataSourceError(f"浏览器启动失败: {exc}") from exc

    async def _new_page(self, marketplace: str = "amazon.com"):
        await self._ensure_browser()
        context = await self._browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await context.add_init_script(_STEALTH_JS)
        # Amazon 按出口 IP 猜国家/货币（如日本出口会显示 JPY 定价）。用 i18n-prefs
        # cookie 锁定为目标站点的货币，保证价格按站点币种展示、可复现。
        currency = _MARKET_CURRENCY.get(marketplace, "USD")
        try:
            await context.add_cookies([{
                "name": "i18n-prefs", "value": currency,
                "domain": f".{marketplace}", "path": "/",
            }])
        except Exception as exc:  # cookie 设置失败不阻断抓取
            logger.debug("设置 i18n-prefs cookie 失败: %s", exc)
        return context, await context.new_page()

    async def _throttle(self):
        await asyncio.sleep(
            random.uniform(self.settings.scraper_min_delay, self.settings.scraper_max_delay)
        )

    async def _debug_shot(self, page, tag: str) -> None:
        """抓取异常时存一张整页截图，便于事后判断是验证码/布局变化/空页。失败静默。"""
        if not _DEBUG_SHOTS:
            return
        try:
            _SHOT_DIR.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = _SHOT_DIR / f"{ts}_{tag}.png"
            await page.screenshot(path=str(path), full_page=True)
            logger.warning("已存调试截图: %s", path)
        except Exception as exc:  # 截图失败绝不影响主流程
            logger.debug("调试截图失败: %s", exc)

    # ============ 列表页 ============
    async def search_top_products(
        self, keyword: str, marketplace: str, limit: int = 10
    ) -> List[Product]:
        """抓取搜索结果 TOP N，失败重试一次（换新 context）后才放弃。"""
        last_err: Optional[Exception] = None
        for attempt in range(2):
            try:
                return await self._search_once(keyword, marketplace, limit)
            except DataSourceError as exc:
                last_err = exc
                logger.warning("爬虫搜索第 %d 次失败: %s", attempt + 1, exc)
        raise DataSourceError(f"爬虫搜索失败（已重试）: {last_err}")

    async def _search_once(
        self, keyword: str, marketplace: str, limit: int
    ) -> List[Product]:
        context, page = await self._new_page(marketplace)
        currency = _MARKET_CURRENCY.get(marketplace, "USD")
        try:
            url = f"https://www.{marketplace}/s?k={keyword.replace(' ', '+')}"
            try:
                await page.goto(
                    url, timeout=self.settings.scraper_timeout_ms, wait_until="domcontentloaded"
                )
            except Exception as exc:
                raise DataSourceError(f"打开 Amazon 页面失败: {exc}") from exc
            await self._throttle()

            if await self._is_blocked(page):
                await self._debug_shot(page, "blocked")
                raise DataSourceError("被 Amazon 拦截（验证码/机器人检测）")

            try:
                await page.wait_for_selector(
                    "div[data-component-type='s-search-result']", timeout=8000
                )
            except Exception:
                pass

            cards = await page.query_selector_all("div[data-component-type='s-search-result']")
            products: List[Product] = []
            seen: set[str] = set()
            organic = 0
            sponsored = 0
            for card in cards:
                if len(products) >= limit:
                    break
                asin = await card.get_attribute("data-asin")
                if not asin or asin in seen:
                    continue
                title_el = await card.query_selector("h2 span")
                title = (await title_el.inner_text()).strip() if title_el else ""
                if not title:
                    continue
                seen.add(asin)

                # 广告位不再跳过：保留并区分 自然排名 / 广告排名
                is_sp = await self._is_sponsored(card)
                if is_sp:
                    sponsored += 1
                    organic_rank, sponsored_rank = None, sponsored
                else:
                    organic += 1
                    organic_rank, sponsored_rank = organic, None

                price_text = await self._price_text(card)
                price = _parse_money(price_text) if price_text else None
                cur = _parse_currency(price_text, currency) if price_text else currency
                list_price = await self._parse_list_price(card)
                if not (price and list_price and list_price > price):
                    list_price = None
                discount = round((1 - price / list_price) * 100, 1) if list_price else None

                is_prime = await card.query_selector("i.a-icon-prime") is not None
                products.append(Product(
                    search_context=SearchContext(
                        keyword=keyword, organic_rank=organic_rank, sponsored_rank=sponsored_rank,
                    ),
                    base_info=BaseInfo(
                        product_id=asin,
                        platform="amazon",
                        title=title,
                        brand=None,  # 详情页 byline 补全
                        image_url=await self._attr(card, "img.s-image", "src"),
                        product_url=f"https://www.{marketplace}/dp/{asin}",
                        rating=await self._parse_rating(card),
                        review_count=await self._parse_review_count(card),
                        badges=await self._parse_badges(card),
                        platform_extra={"is_prime": is_prime},
                    ),
                    pricing=Pricing(
                        price=price,
                        list_price=list_price,
                        currency=cur,
                        discount_pct=discount,
                        coupon=await self._parse_card_coupon(card),
                        fast_shipping=is_prime,
                    ),
                ))
            if not products:
                await self._debug_shot(page, "empty")
                raise DataSourceError("未解析到任何产品（页面结构可能变化或被拦截）")
        finally:
            await context.close()
        return products

    # ============ 详情页 ============
    async def fetch_detail(self, product: Product, marketplace: str) -> None:
        """打开 /dp/{id} 补全 排名/品牌/父体/物流/内容。失败不抛错，尽力而为。"""
        pid = product.base_info.product_id
        context, page = await self._new_page(marketplace)
        try:
            url = f"https://www.{marketplace}/dp/{pid}"
            await page.goto(url, timeout=self.settings.scraper_timeout_ms, wait_until="domcontentloaded")
            await self._throttle()
            if await self._is_blocked(page):
                await self._debug_shot(page, f"detail_blocked_{pid}")
                return

            # 品牌（byline）
            if not product.base_info.brand:
                product.base_info.brand = await self._detail_brand(page)
            # 父体（从页面源码里找）
            product.base_info.parent_id = await self._parent_asin(page)
            # 销量排名 主 + 子节点
            main_rank, main_node, subs = await self._parse_bsr(page)
            product.base_info.rank = main_rank
            product.base_info.rank_category = main_node
            product.base_info.rank_sub_nodes = subs
            # 物流：卖家 / 发货模式 / 尺寸 / 重量
            product.logistics = Logistics(
                seller=await self._buybox_seller(page),
                fulfillment=await self._fulfillment(page),
                dimensions=await self._detail_field(page, ["Product Dimensions", "Package Dimensions"]),
                weight=_parse_weight_lbs(await self._detail_field(page, ["Item Weight"]) or ""),
            )
            # 内容：卖点 / 描述 / 富文本 / 图片数 / 视频 / 变体
            product.content = Content(
                bullet_points=await self._bullets(page),
                description=await self._text_of(page, "#productDescription"),
                rich_content=(await self._text_of(page, "#aplus, .aplus-v2") or None),
                image_count=await self._image_count(page),
                has_video=await self._has_video(page),
                child_id=pid,
                variant_attributes=await self._variants(page),
            )
            # 评论：/product-reviews 页需登录，改从详情页内嵌的 "Top reviews" 抓
            product.reviews_sample = await self._extract_reviews(
                page, pid, self.settings.review_sample_size)
        except Exception as exc:
            logger.warning("抓取详情失败 id=%s: %s", pid, exc)
        finally:
            await context.close()

    # ============ 评论 ============
    async def fetch_reviews(
        self, product_id: str, marketplace: str, limit: int = 40
    ) -> List[Review]:
        """独立抓评论（当未开启 include_detail 时用）。

        注意：Amazon 的 /product-reviews 页现已需登录，故改从详情页 /dp 内嵌的
        "Top reviews" 抓取（通常 8-10 条，无需登录）。
        """
        context, page = await self._new_page(marketplace)
        try:
            url = f"https://www.{marketplace}/dp/{product_id}"
            await page.goto(url, timeout=self.settings.scraper_timeout_ms, wait_until="domcontentloaded")
            await self._throttle()
            if await self._is_blocked(page):
                return []
            return await self._extract_reviews(page, product_id, limit)
        except Exception as exc:
            logger.warning("抓取评论失败 id=%s: %s", product_id, exc)
            return []
        finally:
            await context.close()

    async def _extract_reviews(self, page, product_id: str, limit: int) -> List[Review]:
        """从当前页面（详情页/评论页均可）解析 div[data-hook='review']。

        详情页的评论区常懒加载，先滚到底触发加载并等待评论节点出现。
        """
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_selector("div[data-hook='review']", timeout=6000)
        except Exception:
            pass  # 无评论或加载超时都不阻断
        out: List[Review] = []
        for el in await page.query_selector_all("div[data-hook='review'], div[data-hook='cmps-review']"):
            if len(out) >= limit:
                break
            # 详情页内嵌评论的正文 hook 与独立评论页不同，兼容多种选择器
            body_el = await el.query_selector(
                "span[data-hook='review-body'] span, span[data-hook='review-body'], "
                "span.review-text-content span, [class*='review-text-content'], [class*='review-text']")
            body = (await body_el.inner_text()).strip() if body_el else ""
            if not body:
                continue
            out.append(Review(
                product_id=product_id,
                review_id=await el.get_attribute("id"),
                author=await self._inner_or_none(el, "span.a-profile-name"),
                rating=await self._review_rating(el),
                title=await self._review_title(el),
                body=body,
                date=await self._review_date(el),
                country=await self._review_country(el),
                variant_purchased=await self._inner_or_none(
                    el, "a[data-hook='format-strip'], [data-hook='format-strip']"),
                helpful_votes=await self._review_helpful(el),
                has_buyer_media=await el.query_selector(
                    ".review-image-tile, [data-hook='review-image-tile']") is not None,
            ))
        return out

    # ============ 问答（多数已下线，尽力而为）============
    async def fetch_qa(self, product_id: str, marketplace: str, limit: int = 10) -> List[QA]:
        context, page = await self._new_page(marketplace)
        try:
            url = f"https://www.{marketplace}/ask/questions/asin/{product_id}"
            await page.goto(url, timeout=self.settings.scraper_timeout_ms, wait_until="domcontentloaded")
            await self._throttle()
            if await self._is_blocked(page):
                return []
            out: List[QA] = []
            for blk in await page.query_selector_all("div.a-section.askTeaserQuestions > div"):
                if len(out) >= limit:
                    break
                spans = await blk.query_selector_all("span")
                texts = [(await s.inner_text()).strip() for s in spans]
                texts = [t for t in texts if t]
                if not texts:
                    continue
                out.append(QA(question_text=texts[0], answer_text=texts[1] if len(texts) > 1 else None))
            return out
        except Exception as exc:
            logger.debug("抓取问答失败/无问答 id=%s: %s", product_id, exc)
            return []
        finally:
            await context.close()

    # ---- 列表页解析辅助 ----
    async def _attr(self, root, selector: str, attr: str) -> Optional[str]:
        el = await root.query_selector(selector)
        return await el.get_attribute(attr) if el else None

    async def _is_sponsored(self, card) -> bool:
        if await card.query_selector("[class*='sponsored'], [data-component-type='sp-sponsored-result']"):
            return True
        label = await card.query_selector("span.puis-label-popover-default, a.puis-sponsored-label-text")
        if label and "sponsored" in (await label.inner_text()).lower():
            return True
        return False

    async def _parse_badges(self, card) -> List[str]:
        """Best Seller / Amazon's Choice 等徽章。"""
        badges: List[str] = []
        for el in await card.query_selector_all("span.a-badge-text, span.a-badge-label-inner"):
            t = (await el.inner_text()).strip()
            if t and t not in badges:
                badges.append(t)
        # Amazon's Choice 徽章文案有时在 aria-label 里
        ac = await card.query_selector("[aria-label*=\"Amazon's Choice\"], span.a-badge[aria-label]")
        if ac:
            lbl = await ac.get_attribute("aria-label")
            if lbl and "Choice" in lbl and "Amazon's Choice" not in badges:
                badges.append("Amazon's Choice")
        return badges

    async def _parse_card_coupon(self, card) -> Optional[Coupon]:
        el = await card.query_selector("[class*='coupon'] , span.s-coupon-highlight-color")
        if not el:
            return None
        text = (await el.inner_text()).strip()
        if not text:
            return None
        pct = re.search(r"(\d+)\s*%", text)
        amt = re.search(r"[$£€]\s*([\d.]+)", text)
        if pct:
            return Coupon(type="percent", value=float(pct.group(1)), text=text)
        if amt:
            return Coupon(type="fixed", value=float(amt.group(1)), text=text)
        return Coupon(text=text)

    async def _price_text(self, card) -> Optional[str]:
        el = await card.query_selector("span.a-price:not(.a-text-price) span.a-offscreen")
        if not el:
            el = await card.query_selector("span.a-price span.a-offscreen")
        if not el:
            return None
        return await el.text_content()

    async def _parse_list_price(self, card) -> Optional[float]:
        el = await card.query_selector("span.a-price.a-text-price span.a-offscreen")
        if not el:
            return None
        return _parse_money(await el.text_content())

    async def _parse_rating(self, card) -> Optional[float]:
        el = await card.query_selector("span.a-icon-alt")
        if not el:
            return None
        m = re.search(r"([\d.]+)", await el.inner_text())
        return float(m.group(1)) if m else None

    async def _parse_review_count(self, card) -> Optional[int]:
        el = await card.query_selector("a[href*='#customerReviews']")
        text = (await el.get_attribute("aria-label")) if el else None
        if not text:
            alt = await card.query_selector("span.a-size-base.s-underline-text")
            text = await alt.inner_text() if alt else None
        if not text:
            return None
        m = re.search(r"[\d,\.]+", text)
        return int(m.group().replace(",", "").replace(".", "")) if m else None

    # ---- 详情页解析辅助 ----
    async def _text_of(self, page, selector: str) -> Optional[str]:
        el = await page.query_selector(selector)
        if not el:
            return None
        t = (await el.inner_text()).strip()
        return t[:4000] if t else None  # A+/描述可能很长，截断省存储

    async def _inner_or_none(self, root, selector: str) -> Optional[str]:
        el = await root.query_selector(selector)
        if not el:
            return None
        t = (await el.inner_text()).strip()
        return t or None

    async def _detail_brand(self, page) -> Optional[str]:
        el = await page.query_selector("#bylineInfo")
        if el:
            b = _clean_brand(await el.text_content() or "")
            if b:
                return b
        for row in await page.query_selector_all(
                "#productOverview_feature_div tr, #detailBullets_feature_div li"):
            text = (await row.text_content() or "").strip()
            if re.search(r"brand|品牌|ブランド", text, re.I):
                val = re.split(r"brand|品牌|ブランド|[:：]", text, flags=re.I)[-1].strip()
                cleaned = _clean_brand(val)
                if cleaned:
                    return cleaned
        return None

    async def _parent_asin(self, page) -> Optional[str]:
        try:
            html = await page.content()
        except Exception:
            return None
        m = re.search(r'"parentAsin"\s*:\s*"([A-Z0-9]{10})"', html)
        return m.group(1) if m else None

    async def _bsr_text(self, page) -> str:
        """把可能含 BSR 的几个容器文本拼起来；找不到再回退到整页文本。"""
        parts: List[str] = []
        for sel in ["#productDetails_detailBullets_sections1",
                    "#productDetails_db_sections",
                    "#detailBulletsWrapper_feature_div",
                    "#detailBullets_feature_div",
                    "#prodDetails", "#SalesRank"]:
            el = await page.query_selector(sel)
            if el:
                parts.append(await el.inner_text())
        text = "\n".join(parts)
        if "Best Sellers Rank" not in text and "Seller Rank" not in text:
            try:  # BSR 位置多变，整页文本兜底
                text = await page.inner_text("body")
            except Exception:
                pass
        return text

    async def _parse_bsr(self, page):
        text = await self._bsr_text(page)
        idx = text.find("Best Sellers Rank")
        if idx < 0:
            idx = text.find("Seller Rank")
        seg = text[idx:idx + 400] if idx >= 0 else ""
        matches = re.findall(r"#\s*([\d,]+)\s+in\s+([^(#\n]+)", seg)
        if not matches:
            return None, None, []
        main_rank = int(matches[0][0].replace(",", ""))
        main_node = matches[0][1].strip()
        subs = [RankNode(node=n.strip(), rank=int(r.replace(",", "")))
                for r, n in matches[1:]]
        return main_rank, main_node, subs

    async def _detail_field(self, page, labels: List[str]) -> Optional[str]:
        """从商品详情表/要点里按标签取值（如 'Item Weight' / 'Product Dimensions'）。"""
        rows = await page.query_selector_all(
            "#productDetails_techSpec_section_1 tr, #productDetails_detailBullets_sections1 tr, "
            "#detailBullets_feature_div li, #productOverview_feature_div tr")
        for row in rows:
            text = (await row.text_content() or "").strip()
            for label in labels:
                if label.lower() in text.lower():
                    val = re.split(re.escape(label), text, flags=re.I)[-1]
                    val = val.strip(" :：\n\t")
                    val = " ".join(val.split())
                    if val:
                        return val[:120]
        return None

    async def _buybox_seller(self, page) -> Optional[str]:
        for sel in ["#sellerProfileTriggerId",
                    "#tabular-buybox .tabular-buybox-text[tabular-attribute-name='Sold by'] a",
                    "#tabular-buybox .tabular-buybox-text[tabular-attribute-name='Sold by']",
                    "#merchant-info a", "#bylineInfo_feature_div a"]:
            el = await page.query_selector(sel)
            if el:
                t = (await el.inner_text()).strip()
                if t:
                    return t[:80]
        return None

    async def _fulfillment(self, page) -> Optional[str]:
        el = await page.query_selector(
            "#tabular-buybox, #merchant-info, #fulfillerInfoFeature_feature_div, #offerDisplayFeatures")
        text = (await el.inner_text()).lower() if el else ""
        if not text:
            return None
        ships_amazon = "ships from amazon" in text or "amazon.com" in text
        sold_amazon = "sold by amazon" in text
        if ships_amazon and sold_amazon:
            return "Amazon"
        if "fulfilled by amazon" in text or ships_amazon:
            return "FBA"
        return "FBM"

    async def _bullets(self, page) -> List[str]:
        out: List[str] = []
        for el in await page.query_selector_all(
                "#feature-bullets li:not(.aok-hidden) span.a-list-item"):
            t = (await el.inner_text()).strip()
            if t:
                out.append(t)
        return out[:8]

    async def _image_count(self, page) -> Optional[int]:
        thumbs = await page.query_selector_all("#altImages li.imageThumbnail, #altImages li.item")
        n = len(thumbs)
        return n or None

    async def _has_video(self, page) -> bool:
        return await page.query_selector(
            "#altImages .videoThumbnail, li.videoBlockIngress, .vse-video-container") is not None

    async def _variants(self, page) -> Optional[Dict[str, str]]:
        """从 twister 面板读当前选中的变体维度（尽力而为）。"""
        out: Dict[str, str] = {}
        for row in await page.query_selector_all("#twister .a-row, #twisterContainer .a-row"):
            label_el = await row.query_selector("label, .a-form-label")
            val_el = await row.query_selector(".selection, .a-color-base")
            if label_el and val_el:
                k = (await label_el.inner_text()).strip().rstrip(":：")
                v = (await val_el.inner_text()).strip()
                if k and v and len(k) < 30:
                    out[k] = v
        return out or None

    # ---- 评论解析辅助 ----
    async def _review_rating(self, el) -> Optional[float]:
        r = await el.query_selector("i[data-hook='review-star-rating'] span, i[data-hook='cmps-review-star-rating'] span")
        if not r:
            return None
        m = re.search(r"([\d.]+)", await r.inner_text())
        return float(m.group(1)) if m else None

    async def _review_title(self, el) -> Optional[str]:
        t = await el.query_selector("a[data-hook='review-title'] span, span[data-hook='review-title']")
        return (await t.inner_text()).strip() if t else None

    async def _review_date(self, el) -> Optional[str]:
        d = await el.query_selector("span[data-hook='review-date']")
        return (await d.inner_text()).strip() if d else None

    async def _review_country(self, el) -> Optional[str]:
        d = await el.query_selector("span[data-hook='review-date']")
        if not d:
            return None
        text = (await d.inner_text()).strip()
        m = re.search(r"in (?:the )?([A-Za-z ]+?) on ", text)
        return m.group(1).strip() if m else None

    async def _review_helpful(self, el) -> Optional[int]:
        h = await el.query_selector("span[data-hook='helpful-vote-statement']")
        if not h:
            return None
        text = await h.inner_text()
        m = re.search(r"([\d,]+)", text)
        return int(m.group(1).replace(",", "")) if m else None

    async def _is_blocked(self, page) -> bool:
        title = (await page.title()).lower()
        if "robot" in title or "captcha" in title or "sorry" in title:
            return True
        return await page.query_selector(
            "form[action*='validateCaptcha'], input#captchacharacters") is not None

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None
