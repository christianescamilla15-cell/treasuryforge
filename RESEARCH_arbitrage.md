# treasuryforge — Deep Research: Micro-Arbitrage Reality Check

## Veredicto

No. The "10-20% profit per operation in seconds" premise for cross-exchange and triangular crypto arbitrage is a myth that maps directly to a documented fraud signature, not a real edge. Peer-reviewed evidence (Binance, 30.9M quotes, one week, 2024 data) shows real triangular spreads are 2-3 orders of magnitude smaller: ~89% of opportunities are 0-0.025% gross pre-fee, the single best of the entire week was under 0.5%, and after fees only 18 of 4,879 stayed profitable for a retail trader, netting 12-30 USD for the WHOLE WEEK with a 146ms execution window that structurally favors latency-advantaged firms. Open-source tooling (Hummingbot) productizes real mechanical edges (funding-rate carry, market-making with thresholds) but publishes ZERO demonstrated returns; the only public live-test numbers show ~+2.75%/5-days net ($5.50 on $200 cross-exchange) and an outright LOSS on small-cap DEX arb due to gas. For treasuryforge specifically: at Bitso's retail tier (0.780% MXN taker = ~1.56% round-trip, or even the unusually-low 0.15-0.20% BTC round-trip floor on Bitso Alpha) the fee floor plus slippage, transfer latency, and pre-positioned-capital requirements structurally erase micro cross-app arbitrage edges for a solo small-capital builder — this is a distraction, not an edge to build 24/7 infra around. The mechanical strategies that can in principle clear the fee floor are NOT spot price-grabs but funding-rate carry, maker-rebate market-making, and statistical arb — and even those are thin and capital/operationally demanding.

## Hallazgos verificados (11)

### 1. Real triangular arbitrage spreads on a liquid CEX are 2-3 orders of magnitude smaller than '10-20%' — ~89% of opportunities are 0-0.025% gross pre-fee, and the single best opportunity in an entire week was under 0.5%.

*confianza: high · voto adversarial: 3-0*

Peer-reviewed study (Muck, Schmidl & Wolf 2025, Finance Research Letters v73, Elsevier) on 30.9M Binance BTC/LTC/USD quotes over one week (June 2024): of 4,879 triangular opportunities, 4,337 (88.89%) returned 0-0.025% gross pre-fee and only 3 exceeded 0.5%. 0.025% modal vs 10% target = ~400x gap. Verbatim-confirmed against open-access PDF.

Fuentes: https://www.sciencedirect.com/science/article/pii/S154461232401537X

### 2. After fees, centralized-exchange triangular arbitrage is essentially unexploitable: 96.93% of opportunities are unprofitable even for the lowest-fee VIP-9 tier (>=4B USD/month volume), and only 18 of 4,879 stayed profitable for a retail trader across an entire week.

*confianza: high · voto adversarial: 3-0*

Same primary paper: 'we find that 96.93 percent of the triangular arbitrage opportunities are not even profitable for VIP 9 traders.' For a regular retail trader only 18 of 4,879 opportunities remained profitable across the whole week. Independently corroborated; the only contrary sources were vendor SEO bot/scanner marketing that themselves cite 0.1-0.5% per trade, NOT 10-20%.

Fuentes: https://www.sciencedirect.com/science/article/pii/S154461232401537X

### 3. Total net profit from a whole week of CEX triangular arbitrage is tens of dollars, capped by order-book depth — 12.43-30.42 USD for a retail trader (avg tradable 4,070.86 USD/opportunity), and at most 170.76 USD for VIP-9, which is negligible against the >=4B USD/month turnover required to reach that tier.

*confianza: high · voto adversarial: 3-0*

Primary paper Panel C: regular-trader total net profit span 12.43/17.73/30.42/4.77 USD for the entire week; VIP-9 best case 170.76 USD; average tradable amount 4,070.86 USD across the 18 opportunities. Paper explicitly calls the VIP profit 'negligible' given the 4B USD/month turnover condition. Every figure verbatim-confirmed.

Fuentes: https://www.sciencedirect.com/science/article/pii/S154461232401537X

### 4. Opportunities are too short-lived for retail and require a latency advantage: ~65% last <=1 second, the full triangular leg must execute within 146ms or slippage turns it into an expected loss, and the researchers had to move their server from Europe (80ms) to Tokyo (4ms) to observe them reliably.

*confianza: high · voto adversarial: 3-0*

Primary paper: ~65% of opportunities last <=1s; 'a trader needs to execute the triangular arbitrage strategy in not more than 146 milliseconds to be profitable. Otherwise, the slippage risk would exceed the profitability'; server moved Europe 80ms -> Tokyo 4ms. Paper concludes 'realistically, no trader is fast enough.' This is a hard structural advantage for latency/co-location firms.

Fuentes: https://www.sciencedirect.com/science/article/pii/S154461232401537X

### 5. The peer-reviewed conclusion is that centralized crypto markets are essentially arbitrage-free for triangular strategy — transaction costs, order-book depth, and latency eliminate exploitable profit, and the raw COUNT of 'opportunities' is a weak/unreliable indicator of real inefficiency.

*confianza: high · voto adversarial: 3-0*

Primary paper: 'transaction costs and limited trading volumes in the order book eliminate their profitability. Consequently, centralized cryptocurrency markets exhibit a high degree of efficiency... the mere number of triangular arbitrage opportunities is not a reliable indicator of market inefficiency.' Corroborated by arxiv 2002.12274 (triangular net ~9.3bps, indirect ~11.8bps). Scope is correctly limited to triangular CEX; cross-exchange/DEX-CEX is a different (still thin) strategy.

Fuentes: https://www.sciencedirect.com/science/article/pii/S154461232401537X, https://arxiv.org/abs/2002.12274

### 6. The leading open-source arbitrage frameworks (Hummingbot and its forks) document functionality only — NO backtest results, demonstrated returns, profit figures, or performance metrics — so there is no open-source 'demonstrated 10-20% per trade' evidence to be found.

*confianza: high · voto adversarial: 3-0*

github.com/ailabph/hummingbot-backtest (a Hummingbot fork) names 'Cross Exchange Market Making' and 'AMM Arbitrage' templates but publishes zero quantified performance despite the 'backtest' name. Hummingbot's own 1.27.0 release notes and Arbitrage Executor docs describe mechanism only, no returns/backtests/risk warnings. Liquidity-mining '10-50%' figures are explicitly simulation/whitepaper-based, not empirical (early campaign data: ~$1.96/day average miner reward). Retention (~40% still running at 1 month) is used as a soft profitability proxy, not disclosed P&L.

Fuentes: https://github.com/ailabph/hummingbot-backtest, https://hummingbot.org/release-notes/1.27.0/, https://hummingbot.org/blog/demystifying-liquidity-mining-rewards/, https://hummingbot.org/blog/does-community-based-market-making-work/

### 7. Real mechanical edges that exist in productized open-source tooling are NOT spot cross-exchange price-grabs but funding-rate carry and threshold-gated market-making — and they only enter trades that clear a user-configured profitability threshold net of costs.

*confianza: high · voto adversarial: 3-0*

Hummingbot 1.27.0 ships a funding-rate arbitrage strategy that 'works by exploiting differences in funding rates across different cryptocurrency exchanges' and 'compares it against a profitability threshold.' GitHub master scripts/v2_funding_rate_arb.py gates entry on min_funding_rate_profitability (default 0.001) and exit on profitability_to_take_profit (default 0.01). This is a real, productized mechanism distinct from the 10-20% spot myth — but the source does NOT assert it is highly profitable net of fees/slippage/pre-positioned capital.

Fuentes: https://hummingbot.org/release-notes/1.27.0/

### 8. The only public live-test numbers for retail Hummingbot arbitrage show tiny or negative returns: cross-exchange ETH on $200 over 5 days netted +$5.50 (~2.75% over 5 days, NOT per-trade), with 3-8s windows and 6 of 23 opportunities killed by slippage; small-cap DEX (Uniswap V3) arb on $100 over 48h LOST -$16.50 because L1 gas made every trade net-negative.

*confianza: medium · voto adversarial: 2-1 / 3-0*

gncrypto.news affiliate review (Feb 2026) reports the cross-exchange ETH test (+$5.50 net, 17/23 executed, 200-400ms latency) and the DEX loss (-$16.50, gas as 'the ultimate alpha killer'). Practical profitability thresholds used are ~0.5% (an order of magnitude below 10-20%), with slippage routinely rejecting a large share of opportunities (3-0 vote). CAVEAT: dollar figures come from a single unaudited affiliate self-report with no trade confirmations; cite as 'one reviewer's self-reported test,' but the magnitude (tiny/negative) is directionally corroborated by multiple sources.

Fuentes: https://www.gncrypto.news/trading-bots/hummingbot-review/

### 9. Bitso's retail fee floor structurally destroys micro-arbitrage: at <20,000 MXN 30-day volume, MXN pairs cost 0.600% maker / 0.780% taker (a ~1.56% taker round-trip); even Bitso's unusually low BTC Alpha rates (0.075%/0.098%) give a ~0.15-0.20% same-exchange round-trip floor before slippage/transfer — and a real cross-exchange leg pays the second venue's typically higher fee.

*confianza: high · voto adversarial: 3-0 / 2-1*

Bitso official fee page confirms MXN base tier 0.600%/0.780% (down to 0.100%/0.130% only above 150M MXN volume) and BTC Alpha 0.075%/0.098%. A 1.56% MXN taker round-trip exceeds any plausible liquid-market spread (<1%). The 0.15-0.20% BTC figure is the same-exchange best case; true cross-exchange cost is higher because the second exchange (most MX/global venues 0.1-0.5%+ taker) charges its own fee. The low fee tiers are effectively unreachable for capital chico.

Fuentes: https://support.bitso.com/hc/en-us/articles/4414985686036-What-are-the-Maker-Taker-fees-and-how-do-they-work-on-Bitso, https://www.fxempire.com/exchanges/bitso

### 10. Realistic arbitrage edges everywhere are razor-thin, dominated by fees/gas not the raw spread: a $200M DAI flash-loan multi-leg DeFi arb (Aave/Curve/Balancer) netted only $3.24 after ~$28.76+$1 fees consumed ~90% of the $33 gross gain — and a displayed spread is never profit until both legs execute, funds transfer, and all fees/taxes are counted.

*confianza: high · voto adversarial: 3-0 / 2-1*

Multiple Tier-1 outlets (CoinDesk, The Block, Decrypt, Cointelegraph, fxstreet) confirm the June 2023 MEV bot: $33 gross, ~$29.76 fees, $3.24 net (~0.14% on the ~$2,300 real WETH exposure, still nowhere near 10-20%). CryptoSlate: 'A displayed spread is not profit until both sides execute, funds move, and every fee and tax event is counted.' Transfer latency (10-60 min) lets spreads reverse before both legs settle. CAVEAT: the DeFi case is atomic on-chain MEV (gas-dominated), not Bitso-style CEX arb (taker-fee + withdrawal-latency dominated) — illustrative of thin margins, not direct CEX evidence.

Fuentes: https://www.fxstreet.com/cryptocurrencies/news/crypto-trading-bot-borrows-200m-for-a-3-gain-202306151114, https://cryptoslate.com/guides/crypto-arbitrage/

### 11. '10-20% per microtransaction in seconds' and guaranteed daily/monthly returns from an 'arbitrage bot' are a documented FRAUD signature — most famously the Trade Coin Club MLM Ponzi, which did no trading at all and paid withdrawals purely from new deposits.

*confianza: high · voto adversarial: 3-0 / 2-1*

SEC Press Release 2022-201: Trade Coin Club, a 2016-2018 MLM with a worldwide promoter network, lured investors claiming its bot made 'millions of microtransactions' every second with 'minimum returns of 0.35 percent daily'; in reality 'investor withdrawals came entirely from deposits made by investors, not from any crypto asset trading activity by a bot or otherwise' — a ~$295M / 82,000+ BTC / 100,000+ victim Ponzi. CryptoSlate/CFTC list 'guaranteed daily or monthly profit percentages' and 'automated returns and unrealistic profit guarantees' as explicit red flags. How to distinguish real edge: real arb is 0.1-0.5%/trade gross with execution risk and no guarantees; scams promise fixed high % + microtransaction-bot narrative + MLM/referral.

Fuentes: https://www.sec.gov/news/press-release/2022-201, https://cryptoslate.com/guides/crypto-arbitrage/
