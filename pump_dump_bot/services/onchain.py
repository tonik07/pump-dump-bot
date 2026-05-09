"""
On-chain мониторинг крупных DEX сделок.
Отслеживает Uniswap (ETH) и PancakeSwap (BSC) через бесплатные публичные API.
Даёт преимущество — крупные покупки на DEX часто предшествуют памп на Binance.
"""
import asyncio
import aiohttp
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Бесплатные публичные Graph API
UNISWAP_V3_URL = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"
PANCAKESWAP_URL = "https://api.thegraph.com/subgraphs/name/pancakeswap/exchange-v3-bsc"

# Минимальная сумма сделки в USD
MIN_TRADE_USD = 100_000

# Кэш уже отправленных алертов (чтобы не дублировать)
_sent_alerts: set = set()
_last_scan_time: float = 0


@dataclass
class DexTrade:
    tx_hash: str
    network: str          # ETH / BSC
    dex: str              # Uniswap / PancakeSwap
    token_symbol: str
    token_address: str
    amount_usd: float
    amount_token: float
    side: str             # BUY / SELL
    price_usd: float
    timestamp: int
    wallet: str


UNISWAP_QUERY = """
{
  swaps(
    first: 50
    orderBy: timestamp
    orderDirection: desc
    where: {amountUSD_gt: "%s"}
  ) {
    id
    timestamp
    token0 { symbol id }
    token1 { symbol id }
    amount0
    amount1
    amountUSD
    origin
    transaction { id }
  }
}
""" % MIN_TRADE_USD

PANCAKE_QUERY = """
{
  swaps(
    first: 50
    orderBy: timestamp
    orderDirection: desc
    where: {amountUSD_gt: "%s"}
  ) {
    id
    timestamp
    token0 { symbol id }
    token1 { symbol id }
    amount0
    amount1
    amountUSD
    origin
    transaction { id }
  }
}
""" % MIN_TRADE_USD


async def query_graph(session: aiohttp.ClientSession, url: str, query: str) -> dict:
    try:
        async with session.post(
            url,
            json={"query": query},
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"Content-Type": "application/json"}
        ) as r:
            if r.status == 200:
                return await r.json()
    except Exception as e:
        logger.warning(f"Graph query error {url}: {e}")
    return {}


def parse_swaps(swaps: list, network: str, dex: str) -> list[DexTrade]:
    trades = []
    stables = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP", "GUSD"}

    for swap in swaps:
        try:
            tx_hash = swap.get("transaction", {}).get("id", swap.get("id", ""))
            if tx_hash in _sent_alerts:
                continue

            amount_usd = float(swap.get("amountUSD", 0))
            if amount_usd < MIN_TRADE_USD:
                continue

            token0 = swap.get("token0", {})
            token1 = swap.get("token1", {})
            sym0 = token0.get("symbol", "").upper()
            sym1 = token1.get("symbol", "").upper()
            amt0 = float(swap.get("amount0", 0))
            amt1 = float(swap.get("amount1", 0))

            # Определяем какой токен торгуется (не стейбл)
            if sym0 in stables and sym1 not in stables:
                token_sym = sym1
                token_addr = token1.get("id", "")
                token_amount = abs(amt1)
                side = "BUY" if amt0 < 0 else "SELL"
            elif sym1 in stables and sym0 not in stables:
                token_sym = sym0
                token_addr = token0.get("id", "")
                token_amount = abs(amt0)
                side = "BUY" if amt1 < 0 else "SELL"
            elif sym0 in {"WETH", "WBNB", "ETH", "BNB"} and sym1 not in stables:
                token_sym = sym1
                token_addr = token1.get("id", "")
                token_amount = abs(amt1)
                side = "BUY" if amt0 < 0 else "SELL"
            elif sym1 in {"WETH", "WBNB", "ETH", "BNB"} and sym0 not in stables:
                token_sym = sym0
                token_addr = token0.get("id", "")
                token_amount = abs(amt0)
                side = "BUY" if amt1 < 0 else "SELL"
            else:
                continue

            # Пропускаем стейблы и обёрнутые токены
            skip = {"WETH", "WBNB", "WBTC"} | stables
            if token_sym in skip:
                continue

            price_usd = amount_usd / token_amount if token_amount > 0 else 0
            wallet = swap.get("origin", "unknown")
            timestamp = int(swap.get("timestamp", 0))

            trades.append(DexTrade(
                tx_hash=tx_hash,
                network=network,
                dex=dex,
                token_symbol=token_sym,
                token_address=token_addr,
                amount_usd=amount_usd,
                amount_token=token_amount,
                side=side,
                price_usd=price_usd,
                timestamp=timestamp,
                wallet=wallet,
            ))
        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Parse swap error: {e}")

    return trades


async def scan_dex_trades(min_usd: float = MIN_TRADE_USD) -> list[DexTrade]:
    """Сканируем Uniswap V3 и PancakeSwap на крупные сделки"""
    all_trades = []

    async with aiohttp.ClientSession() as session:
        uni_data, cake_data = await asyncio.gather(
            query_graph(session, UNISWAP_V3_URL, UNISWAP_QUERY),
            query_graph(session, PANCAKESWAP_URL, PANCAKE_QUERY),
            return_exceptions=True
        )

    # Uniswap
    if isinstance(uni_data, dict) and "data" in uni_data:
        swaps = uni_data["data"].get("swaps", [])
        trades = parse_swaps(swaps, "ETH", "Uniswap V3")
        all_trades.extend(trades)
        logger.info(f"Uniswap: найдено {len(trades)} крупных сделок")

    # PancakeSwap
    if isinstance(cake_data, dict) and "data" in cake_data:
        swaps = cake_data["data"].get("swaps", [])
        trades = parse_swaps(swaps, "BSC", "PancakeSwap")
        all_trades.extend(trades)
        logger.info(f"PancakeSwap: найдено {len(trades)} крупных сделок")

    # Сортируем по объёму
    all_trades.sort(key=lambda t: t.amount_usd, reverse=True)

    # Фильтруем только новые
    new_trades = [t for t in all_trades if t.tx_hash not in _sent_alerts]

    # Запоминаем отправленные
    for t in new_trades:
        _sent_alerts.add(t.tx_hash)

    # Чистим кэш (оставляем последние 1000)
    if len(_sent_alerts) > 1000:
        old = list(_sent_alerts)[:500]
        for h in old:
            _sent_alerts.discard(h)

    return new_trades


def format_dex_trade(t: DexTrade) -> str:
    side_emoji = "🟢 ПОКУПКА" if t.side == "BUY" else "🔴 ПРОДАЖА"
    net_emoji = "⟠" if t.network == "ETH" else "🟡"

    if t.amount_usd >= 1_000_000:
        usd_str = f"${t.amount_usd/1_000_000:.2f}M"
        intensity = "🚨 МЕГА КИТ"
    elif t.amount_usd >= 500_000:
        usd_str = f"${t.amount_usd/1_000:.0f}K"
        intensity = "🐋 КРУПНЫЙ КИТ"
    else:
        usd_str = f"${t.amount_usd/1_000:.0f}K"
        intensity = "🐬 КИТ"

    if t.price_usd < 0.001:
        price_str = f"${t.price_usd:.8f}"
    elif t.price_usd < 1:
        price_str = f"${t.price_usd:.4f}"
    else:
        price_str = f"${t.price_usd:.2f}"

    token_str = f"{t.amount_token:,.0f}" if t.amount_token > 1 else f"{t.amount_token:.4f}"

    wallet_short = f"{t.wallet[:6]}...{t.wallet[-4:]}" if len(t.wallet) > 12 else t.wallet

    explorer = f"https://etherscan.io/tx/{t.tx_hash}" if t.network == "ETH" else f"https://bscscan.com/tx/{t.tx_hash}"

    return (
        f"{intensity} на DEX\n"
        f"{'━'*26}\n"
        f"{net_emoji} <b>#{t.token_symbol}</b> — {t.dex}\n"
        f"{side_emoji}\n"
        f"💰 Объём: <b>{usd_str}</b>\n"
        f"🪙 Количество: <code>{token_str}</code> {t.token_symbol}\n"
        f"💵 Цена: <code>{price_str}</code>\n"
        f"👛 Кошелёк: <code>{wallet_short}</code>\n"
        f"🔗 <a href='{explorer}'>Смотреть транзакцию</a>\n\n"
        f"⚡️ <i>Крупная DEX сделка — часто предшествует движению на Binance</i>\n"
        f"⚠️ <i>Не торговый сигнал. DYOR.</i>"
    )
