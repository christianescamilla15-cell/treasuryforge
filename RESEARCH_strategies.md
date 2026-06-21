# treasuryforge — Deep Research: Mechanical Strategy Comparison

## Veredicto

Para un builder solo con capital chico, los números reales net-of-cost desinflan casi todo el hype. Las dos estrategias mecánicas con edge real DOCUMENTADO y construibles en solitario son: (a) carry — funding-carry en perps y cash-and-carry/basis spot-vs-futuros — con retorno modesto pero real (~6-10% APR bruto histórico, episódicamente >40%, pero comprimido en 2025-26 y NO risk-free por riesgo de margen/liquidación), y (b) stat-arb/pairs por cointegración, que tiene edge real pero MODESTO (Sharpe out-of-sample por par ~0.69, NO los 1.53/2.23/3.00 que circulan, todos refutados o in-sample), requiere shorting (perps/margen) y se degrada a ~cero en frecuencia diaria net-of-cost. Market-making (Avellaneda-Stoikov/Cartea-Jaimungal) tiene un agujero teórico confirmado — los modelos estándar IGNORAN adverse selection y price-reading, que son riesgos de primer orden que fuerzan quotes defensivos y degradan el edge — por lo que es lo más expuesto a HFT y lo menos apto para retail sin rebates/colocation. TSMOM cripto reporta Sharpe bruto 2.17/0.94%-día pero esas cifras son brutas (sin costos) y el alpha de TSMOM está "largely driven by volatility scaling", no por la señal: sin vol-scaling el momentum es indistinguible de buy-and-hold. DEX LP concentrado (Uniswap v3) tiene impermanent loss como costo cuantificable de primer orden que debe netearse contra fees, no es yield gratis. Veredicto para treasuryforge (prioridad aprender, no maximizar): el carry (que ya validaste en Hyperliquid) tiene la mejor relación edge/complejidad; stat-arb por cointegración es el mejor SEGUNDO proyecto para aprender (señal real, riguroso, pero exige short e infra de pares); market-making y LP concentrado son los de peor relación edge/complejidad/riesgo para un solo builder.

## Hallazgos (9)

### 1. Cash-and-carry / basis trade (spot vs futuros dated): edge real BRUTO ~7% p.a. promedio cross-exchange (abril 2019-julio 2024), con picos episódicos >40-55% (OKEx) / 45% (CME), pero altamente volátil, NO risk-free (riesgo de margen/funding tipo Brunnermeier-Pedersen: un movimiento adverso del basis antes del vencimiento dispara márgenes y fuerza liquidación), y el CME cayó por debajo de -50% durante el colapso de FTX. El carry se comprimió ~3pp tras el ETF spot de BTC (97% del promedio en CME).

*conf high · voto 3-0 (claims 0,1,2,15,16,17 unánimes)*

BIS WP1087 'Crypto carry' (Schmeling/Schrimpf/Todorov, publicado en Management Science 2024): promedio ~7% p.a. cross-exchange abril 2019-julio 2024, basis 1-mes BTC ~8% OKEx / 6.4% CME con máximos ~55%/~45%; 'cash-and-carry exposes the trader to funding risk... a spike in margins can force a liquidation of the position before convergence'; CME por debajo de -50% en FTX. Driver: demanda de trend-chasers apalancados + escasez de capital de arbitraje del otro lado. ETF spot redujo carry ~3pp (36% del promedio global, 97% en CME).

Fuentes: https://www.bis.org/publ/work1087.pdf, https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets

### 2. Funding-rate carry (perps): baseline real con Sharpe REGIME-DEPENDENT y peligro de venue. El MISMO arbitraje de funding ejecutado en CEX (Binance, Bitmex) produjo Sharpe NEGATIVOS (-7.34 y -7.93) sobre la muestra — es decir, la versión CEX rindió por DEBAJO del risk-free ajustado por riesgo. Los Sharpe altos en DEX (Drift 23.55, ApolloX 6.50) están inflados por ventanas de observación cortas y el Sharpe ignora riesgo de liquidación/gas-competition (ese claim DEX fue refutado 1-2).

*conf high · voto 2-1 (claim 18); claim DEX-alto refutado*

Zhang et al. 2025 (ScienceDirect S2096720925000818): 'corresponding analyses on centralized exchanges demonstrate negative Sharpe Ratios, namely -7.34 (Binance) and -7.93 (Bitmex)'. Muestra BTC/ETH/XRP/BNB/SOL, Bitmex Mar 2015-Feb 2024. Caveat del propio paper: Sharpe negativo = retorno por debajo del risk-free (no necesariamente pérdida absoluta); los altos DEX inflados por ventanas cortas. Nota cruzada: arXiv 2510.14435 reporta funding carry ~8% media Ago2020-May2025 pero NEGATIVO en 2025.

Fuentes: https://www.sciencedirect.com/science/article/pii/S2096720925000818

### 3. Statistical arbitrage / pairs trading por cointegración: edge REAL pero MODESTO. Existen relaciones cointegrantes genuinas en cripto (229 pares identificados vía cointegración + ECM, Ago2021-Ene2024), pero el universo es pequeño y time-varying, y el Sharpe out-of-sample REALISTA por par es ~0.69 — NO los 1.53/2.23 que circularon (refutados) ni el 3.00 de un thesis de bachelor (in-sample/look-ahead, sin modelo de costos propio). Trabajo peer-reviewed previo (Fil-Kristoufek 2020) muestra que en frecuencia DIARIA el edge net-of-cost es ~cero; solo funciona a 5-min (inviable para un solo builder).

*conf high · voto 3-0 (claims 4,5,6,7); 3 sub-claims optimistas refutados 0-3/1-2*

Quantitative Finance 26(5) 2026 (DOI 10.1080/14697688.2026.2653663): 229 pares, 'profitable cointegrating relationships... short-term market inefficiencies', Sharpe out-of-sample por par 0.69, median max DD 15.29%, umbrales GA-optimizados (riesgo overfit). Thesis EUR 67552: 'monthly portfolio return of 12%... annualized Sharpe ratio of 3.00' pero selección de pares por correlación en la MISMA ventana (in-sample), sin modelo propio de slippage/borrow. Fil-Kristoufek 2020 (IEEE Access): diario -0.07%/mes, sube a 11.61%/mes solo a 5-min, 'strongly underperforms previous benchmark literature'.

Fuentes: https://www.tandfonline.com/doi/full/10.1080/14697688.2026.2653663, https://thesis.eur.nl/pub/67552/Thesis-Pairs-trading-.pdf

### 4. Stat-arb/pairs en cripto REQUIERE shorting estructuralmente: las señales abren un long en una pata y un short SIMULTÁNEO en la otra; la implementación canónica corre sobre futuros USDT-margined (Binance), no existe variante long-only/spot manteniendo el hedge. Esto es una restricción práctica dura para treasuryforge, que hoy vive en Bitso SPOT — para pairs necesitarías un venue de perps/margen con capacidad de short.

*conf high · voto 3-0 (claim 12), corroborado claim 11*

Tadi & Witzany, Financial Innovation 2025 (10.1186/s40854-024-00702-7 / arXiv 2305.06961): regla de trade 'open long S1 and short S2', implementado en Binance USDT-margined futures; diseño 20 monedas (BTC ancla vs 19 alts), 104 ciclos rolling (3 sem formación + 1 sem trading), tests EG + KSS lineal/no-lineal + cópulas. Universo de cointegración pequeño y time-varying. No hay variante long-only que preserve neutralidad de mercado.

Fuentes: https://link.springer.com/article/10.1186/s40854-024-00702-7, https://arxiv.org/abs/2305.06961

### 5. Market-making (Avellaneda-Stoikov / Cartea-Jaimungal): los modelos ESTÁNDAR tienen un agujero confirmado — ignoran adverse selection (winner's curse: te llenan en el bid justo antes de que el mercado baje) e information leakage por price-reading, que son riesgos de PRIMER ORDEN en la práctica real. Señales informadas afiladas fuerzan al market maker a mostrar quotes defensivos/más anchos y a comportarse como más averso al riesgo en todo el libro — es decir, adverse selection degrada materialmente el edge del maker salvo que se ensanchen quotes. Esto es exactamente el frente donde el HFT con colocation/rebates domina al retail.

*conf high · voto 3-0 (claims 13,14)*

arXiv 2508.20225 'Optimal Quoting under Adverse Selection and Price Reading' (Barzykin/Bergault/Gueant/Lemmel 2025; Gueant=teórico líder de MM óptimo, Barzykin=practitioner HSBC FX): 'most existing market making models overlook two key challenges... adverse selection and information leakage through price reading'; 'adverse selection with sharp signals forces the market maker to act protectively by showing defensive quotes... behave as if they were more risk averse with their global franchise'. Consistente con Glosten-Milgrom 1985 (componente de adverse selection del spread).

Fuentes: https://arxiv.org/pdf/2508.20225

### 6. Trend/momentum (TSMOM vol-scaled): las cifras brutas son llamativas pero engañosas net-of-cost y por construcción. Un TSMOM cripto volume-weighted reporta 0.94%/día y Sharpe anualizado 2.17, pero el abstract NO declara resultado net-of-cost (son brutas). Más importante: el alpha de TSMOM (Moskowitz-Ooi-Pedersen 2012) está 'largely driven by volatility scaling', no por la señal de momentum; SIN vol-scaling, TSMOM y buy-and-hold dan retornos acumulados similares y alphas estadísticamente indistinguibles — el edge standalone del momentum es débil.

*conf high · voto 3-0 (claims 8,9,10)*

SSRN 4825389 (Huang/Sangiorgi/Urquhart 2024): 'strategy can gain 0.94% per day with an annualized Sharpe ratio of 2.17' (CentAUR confirma que no especifica gross/net ni análisis de costos). Kim-Tse-Wald 2016 (J. Financial Markets/Empirical Finance): 'Large time series momentum alphas... are largely driven by volatility scaling'; 'Without scaling by volatility, time series momentum and a buy-and-hold strategy offer similar cumulative returns, and their alphas are not significantly different' (alpha vol-scaled 1.08-1.27%/mes vs unscaled 0.39-0.41%/mes).

Fuentes: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4825389, https://www.sciencedirect.com/science/article/abs/pii/S1386418116301379

### 7. DEX liquidity provision (Uniswap v3 concentrated LP): el impermanent loss es un costo CUANTIFICABLE de primer orden que debe netearse contra los fees, no un afterthought. La liquidez concentrada deja al LP asignar capital en un rango de precio elegido, pero existe una aproximación analítica para el fee esperado Y el IL esperado bajo ese mecanismo — el yield 'real' es fee_income menos IL, y el rango estrecho que maximiza fees también maximiza exposición a IL. No es yield gratis.

*conf high · voto 3-0 (claim 3)*

Hashemseresht & Pourpouneh, DeFi'22 (ACM CCS Workshop, 10.1145/3560832.3563438): 'allows the liquidity providers to add liquidity within a specific price range... an approximation for the expected fees and the impermanent loss of a liquidity provider'. Corroborado por arXiv 2111.09192 ('Impermanent Loss in Uniswap v3'), arXiv 2205.12043 ('Static Replication of Impermanent Loss'), hal-04214315 — todos tratan IL como costo cuantificable a netear contra fees.

Fuentes: https://dl.acm.org/doi/10.1145/3560832.3563438

### 8. Grid trading / DCA / rebalancing: NO hay evidencia en el corpus verificado de que constituyan un edge estadístico independiente; funcionan como gestión de riesgo / disciplina de ejecución (mean-reversion implícita en rango + reducción de varianza de timing), no como alpha mecánico documentado net-of-cost. Tratarlos como capa de POLÍTICA/EJECUCIÓN dentro de treasuryforge, no como estrategia generadora de edge.

*conf low · voto sin claim primario en el corpus (ausencia de evidencia, no evidencia de ausencia)*

Ninguna de las 19 claims confirmadas ni las 6 refutadas aporta fuente primaria peer-reviewed que documente un edge net-of-cost independiente para grid/DCA/rebalancing. La inferencia (son gestión de riesgo disfrazada, no edge) es consistente con que su retorno depende de la deriva del subyacente, no de una ineficiencia explotable medida. Confianza baja por falta de fuente dedicada en este corpus.

Fuentes: (sin fuente primaria en el corpus verificado)

### 9. RANKING comparativo edge/complejidad para un solo builder con capital chico que prioriza aprender/construir sobre maximizar retorno: (1) Funding-carry en perps — mejor relación, ya validado en Hyperliquid, edge real regime-dependent, infra mínima, riesgo principal = funding negativo/liquidación; (2) Cash-and-carry/basis — mismo nivel conceptual, ~7% bruto histórico, riesgo de margen/inversión del basis, necesita spot+futuros datados; (3) Stat-arb por cointegración — MEJOR segundo proyecto educativo (señal real, riguroso, Sharpe~0.69/par) pero exige shorting/perps e infra de selección de pares y se muere a frecuencia diaria; (4) TSMOM vol-scaled — edge frágil (driven by vol-scaling), útil para aprender risk-parity pero no como alpha; (5) DEX concentrated LP — yield real solo si modelas IL, complejidad y riesgo de smart-contract/IL altos; (6) Grid/DCA/rebalancing — capa de ejecución, no edge; (7) Market-making A-S/grid-MM — PEOR relación: dominado por HFT, adverse selection ignorado por los modelos, requiere rebates/VIP/colocation, no apto para retail solo.

*conf medium · voto síntesis de claims 0-18 (ranking es juicio agregado, no claim único)*

Derivado de: carry tiene edge real documentado y menor complejidad de infra (BIS WP1087); funding-carry ya validado por el usuario en Hyperliquid; stat-arb Sharpe~0.69/par real pero requiere short (Tadi-Witzany) y se degrada en diario (Fil-Kristoufek); TSMOM driven-by-vol-scaling (Kim-Tse-Wald); LP IL de primer orden (DeFi'22); market-making expuesto a adverse selection no modelado + winner's curse (arXiv 2508.20225) = territorio HFT. El ranking pondera edge net-of-cost documentado, complejidad de implementación, capital mínimo, infra/venue y riesgo no-obvio, con peso extra a 'construible y educativo para un solo builder' por la prioridad declarada del usuario.

Fuentes: https://www.bis.org/publ/work1087.pdf, https://www.tandfonline.com/doi/full/10.1080/14697688.2026.2653663, https://arxiv.org/pdf/2508.20225, https://www.sciencedirect.com/science/article/abs/pii/S1386418116301379
