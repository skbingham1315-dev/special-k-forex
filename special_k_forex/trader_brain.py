"""
trader_brain.py
---------------
Synthesized trading knowledge base extracted from 17 classic trading texts.
Used as context for AI-assisted trade signal evaluation.

Sources:
- Wyckoff Method (Richard D. Wyckoff)
- Gann Masters I & II (Halliker's Inc.)
- W.D. Gann Master Commodities Course
- Fibonacci Analysis (Constance Brown)
- Patterns of Gann (Cooley, Granville)
- New Trading Dimensions (Bill Williams)
- Trading Chaos (Bill Williams)
- Encyclopedia of Chart Patterns 2nd Ed. (Thomas Bulkowski)
- Profits in the Stock Market (H.M. Gartley)
- Investing with Volume Analysis (Buff Dormeier)
- Trade Chart Patterns Like the Pros (Suri Duddella)
- Candlesticks, Fibonacci and Chart Pattern Trading Tools (Robert & Jens Fischer)
- The New Fibonacci Trader (Robert Fischer)
- 3 Peaks and a Domed House (George Lindsay)
"""

TRADER_BRAIN = """
================================================================================
SPECIAL K TRADER BRAIN — SYNTHESIZED TRADING KNOWLEDGE BASE
================================================================================

## WYCKOFF METHOD
Source: Richard D. Wyckoff Course of Instruction (1931/1937)

### Core Principle: Supply and Demand
The Basic Law: prices rise when demand exceeds supply; prices fall when supply
exceeds demand. The tape (price + volume) reveals the plans of large operators.
Every price move is caused by an imbalance between buying and selling pressure.
Follow the smart money — do not fight accumulation or distribution campaigns.

### Four Phases of a Market Campaign
1. ACCUMULATION (Phase I): Large operators quietly absorb stock at low prices.
   Signs: narrow trading range, dull volume, no downward progress, occasional
   shakeouts to discourage weak longs. "Tiring out" process. Base building.
2. MARK-UP (Phase II): Bullish position. Price advances with increasing volume.
   Higher bottoms and higher tops. Strong relative strength vs. market.
3. DISTRIBUTION (Phase III): Large operators quietly sell at high prices.
   Signs: wide price swings, high volume with little net progress (churn),
   "preliminary supply" bars, stock acts weak on rallies.
4. MARK-DOWN (Phase IV): Bearish position. Price declines with volume surges.
   Lower tops and lower bottoms. Weak relative to market.

### Wyckoff Buying Tests (9 Conditions for Long Entry)
1. Objective accomplished on the downside (figure chart target reached)
2. Activity bullish — volume increases on rallies, shrinks on reactions
3. Preliminary Support visible (spike volume climax at a low)
4. Stronger than market — responds to rallies, resists reactions
5. Downward stride broken (downtrend supply line penetrated on low volume)
6. Higher supports (rising lows)
7. Higher tops
8. Base forming (horizontal congestion on figure chart)
9. Estimated profit at least 3x the indicated risk (stop placement)

### Wyckoff Selling Tests (9 Conditions for Short Entry)
1. Objective accomplished on the upside
2. Activity bearish — volume increases on reactions, shrinks on rallies
3. Preliminary Supply visible
4. Weaker than market — responsive to reactions, sluggish on rallies
5. Upward stride broken (uptrend support line violated)
6. Lower tops
7. Lower supports (lower highs)
8. Crown forming (lateral distribution on figure chart)
9. Estimated profit at least 3x the indicated risk

### Wyckoff Volume Rules
- Selling Climax: abnormal volume + sharp price drop = demand overcoming supply;
  expect at least a technical rally.
- Buying Climax: abnormal volume + sharp price advance = supply overcoming demand.
- Volume increasing on reactions within uptrend = warning of distribution.
- Volume shrinking on pullbacks within uptrend = healthy; trend likely to continue.
- Terminal Shake-out: final flush below support on huge volume, fast recovery;
  strong buy signal if subsequent rally confirms.
- Effort vs. Result: if large volume produces small price movement, effort is not
  translating to result; trend exhaustion signal.
- Spring: price breaks below support, quickly recovers; confirms accumulation zone.

### Wyckoff Risk Rule
NEVER enter a trade unless estimated probable profit (from figure chart objective)
is at least 3 times the risk (stop distance). Place stops just beyond the last
meaningful support or supply level identified on the vertical chart.

### Wyckoff Price Objectives (Point & Figure)
Count the width of accumulation or distribution base horizontally.
Multiply count by box size to get minimum price objective.
Longer time in preparation = stronger, more ambitious objective.
A 3-month base implies a shorter campaign; a 1-2 year base implies a major move.

---

## GANN PRINCIPLES
Sources: Gann Masters I & II, W.D. Gann Master Commodities Course

### Gann's Fundamental Rules
1. Never risk all capital on one or two trades. Capital preservation is primary.
2. Trade with the MAIN TREND — never against it.
3. Prices are NEVER too high to buy while the trend is UP.
   Prices are NEVER too low to sell while the trend is DOWN.
4. Never trade on hope, fear, or guesswork. Follow mathematical rules.
5. Always use STOP-LOSS orders. Protect profits as fiercely as capital.
6. When a stop is hit, REVERSE position if trend has changed.
7. Avoid trading in the delivery month of futures contracts.

### Gann's 28 Trading Rules (Key Rules)
Rule 1 — TREND LINE INDICATIONS: Buy/sell only when trend indicator confirms.
  Place stop 1-3 points below last trend line bottom (or above top).
Rule 2 — DOUBLE/TRIPLE BOTTOMS: Buy at double or triple bottoms.
  Use 1-3 point stop. Triple bottoms are strongest support.
Rule 3 — DOUBLE/TRIPLE TOPS: Sell at double or triple tops.
  Use 1-3 point stop. Triple tops are strongest resistance.
Rule 4 — FOURTH TIME AT SAME LEVEL: When market reaches same level 4th time,
  it almost always breaks through. Buy breakout above triple top; sell breakdown below triple bottom.
Rule 5 — ASCENDING BOTTOMS: After triple bottom, each higher low is increasingly bullish.
Rule 6 — DESCENDING TOPS: After triple top, each lower high is increasingly bearish.
Rule 7 — 7-10 DAY RULE: After 7-10 consecutive up (or down) days, use 1-point
  trailing stop on each daily high/low.
Rule 8 — PYRAMIDING: Add to position every 5 cents (or equivalent) in your favor
  as long as trend indicator confirms. Stop must always be 1 point from Trend Line.
Rule 9 — THE RUN: Big pyramiding profits come in the run between accumulation
  and distribution. Start pyramids after double/triple bottoms.
Rule 14 — MINOR TREND: 3-day chart defines minor trend.
Rule 15 — MAIN TREND: When a move exceeds the previous move in TIME, the trend
  has likely changed. Watch for time overbalance.
Rule 19 — 3-POINT SIGNAL: After a prolonged move, 3 full-point reversal signal
  from bottom/top indicates change in trend.
Rule 20 — SHARP 2-DAY SIGNAL: 2-day reversal move in opposite direction signals
  a potential trend change (especially after fast moves).
Rule 21 — SIGNAL TOP DAY: Close near the low after an uptrend = signal top day.
Rule 22 — SIGNAL BOTTOM DAY: Close near the high after a downtrend = signal bottom day.
Rule 26 — THREE TOPS/BOTTOMS AT SAME LEVEL: Three closes at the same level =
  very strong signal; prepare for breakout.
Rule 27 — 3-DAY CHART CROSSINGS: Price crossing top or breaking bottom of 3-day
  chart swings = change in minor trend direction.

### Gann Angles
The 1x1 angle (45 degrees) = price moves at same rate as time.
This is the most important angle — market in balance when on 1x1.
Angles FROM A LOW (ascending): 8x1, 4x1, 3x1, 2x1, 1x1, 1x2, 1x3, 1x4, 1x8
Angles FROM A HIGH (descending): same angles in reverse
- Price above 1x1 from a major low = bullish (strong uptrend)
- Price below 1x1 from a major low = bearish (weak)
- When price breaks one angle, it will move to the next
- INTERSECTING ANGLES: where two angles cross = major support/resistance/turning point
- Back-360 Angles: draw angles from highs/lows that are multiples of 360 back
  (45, 90, 135, 180, 270, 360 bars) from current date = natural cycle points

### Gann Support and Resistance
- Divide price range by 2, 3, 4, 8 to find support/resistance levels.
- Halfway point (50%) is ALWAYS the most important level.
- All-time high divided by 3 = major resistance.
- All-time low multiplied by 2 = major support.
- When a resistance level is broken, it becomes support (and vice versa).
- Watch for clusters of different calculations at the same price = very strong S/R.
- Long sideways periods: when price breaks out of a long range,
  expect a major trend change, especially with gaps and high volume.

### Gann Time Cycles
- Key time periods: 30, 45, 60, 90, 120, 144, 180, 270, 360 days/weeks/months.
- When time count from a high or low equals the price of that high or low,
  price and time are "squared" — major turning point likely.
- Watch first 3, 5, 7 days of January (start of year) and July (mid-year) for
  breakout direction — that direction often holds 3-4 months.
- Study extreme high/low years: look for same last digit in year for recurrence.
- 3-day Chart: minor trend; 7-10 week swings: intermediate; monthly: major.
- Fibonacci time counts within market swings: 3, 5, 8, 13, 21, 34 days are natural.
- When time of a reaction EXCEEDS the time of the previous reaction, trend has changed.

### Gann Resistance Levels (Grains, adapted for all markets)
- Range of fluctuation: highest price minus lowest price, divided by 8.
- Key levels: 1/8, 2/8 (25%), 3/8 (37.5%), 4/8 (50%), 5/8 (62.5%), 6/8 (75%), 7/8
- 50% retracement is most critical. 25% and 75% are next most important.
- Multiples of 12 often act as support/resistance (12, 24, 36, 48, 60, 72, 144).

---

## FIBONACCI LEVELS
Sources: Constance Brown (Fibonacci Analysis), Robert Fischer, Suri Duddella

### Core Fibonacci Ratios
- 0.236, 0.382, 0.500, 0.618, 0.786, 0.886
- Extensions: 1.000, 1.272, 1.382, 1.618, 2.000, 2.618, 3.618
- PHI = 1.618 (Golden Ratio); phi = 0.618 (inverse/reciprocal)
- Key for projections: price target = swing size × 1.618 added to swing end.

### Fibonacci Retracements (Constance Brown Rules)
- 38.2% retracement = shallow correction; trend is very strong.
  Price often doesn't reach 50% before resuming the trend.
- 50% retracement = moderate correction; common in normal trends.
- 61.8% retracement = deep correction; if held, trend remains intact.
  If 61.8% is broken, watch 78.6%.
- 78.6% retracement = last line of defense before full reversal.
  If broken with momentum, trend has likely reversed.
- 88.6% retracement = used in Bat harmonic patterns; very deep correction.
- CRITICAL: Oscillators must be used AT THE FIBONACCI LEVEL to confirm.
  Do not take signals prematurely. Wait for market to reach the zone, then
  use RSI, stochastics, or momentum to confirm a trade.

### Fibonacci Confluence Zones
- When multiple Fibonacci measurements (from different swings) cluster near
  the same price level, that zone is significantly stronger support/resistance.
- Method: overlay 38.2%, 50%, 61.8% from different time frames/swings.
  Where they overlap = confluence zone = high-probability trade location.
- Use gaps as measuring levels within Fibonacci analysis.
  Gaps often form at 50% subdivisions of price geometry.

### Fibonacci Extensions (Price Targets)
- 3-wave pattern: multiply initial impulse wave by 1.618 = target for wave 3.
- 5-wave pattern:
  - Wave 5 target: (amplitude of wave 1 × 1.618) combined with
    (amplitude from bottom of wave to top of wave 3 × 0.618)
  - These two calculations give a "Fibonacci price band" for wave 5 end.
  - If the band is too wide relative to wave 1 amplitude, the target is not reliable.
- Mirror geometry: project the range from a key confluence zone downward/upward
  to find the next major target.

### Fibonacci Symmetry (Duddella / Fischer)
- 100% extension: after a retracement of less than 50%, the next leg often
  equals 100% of the first leg (AB = CD symmetry).
- If retracement exceeds 50%, extension may be less than 100%.
- Trade entry: after BC retracement, enter one tick above the B level.
- Stop: one tick below C.
- Target: 100% of AB range from C level.

---

## CHART PATTERNS (Bulkowski + Gartley + Lindsay + Duddella + Fischer)

### Pattern Statistics (Bulkowski — Empirical Data from 38,500+ Samples)
HEAD AND SHOULDERS BOTTOM (Reversal):
- Bull market avg rise: 38% | Bear market avg rise: 30%
- 34% of bull market patterns rise >45% | 24% in bear markets
- Failure rate to reach 5% gain: only 3-4% (very reliable)
- Failure rate to reach 15% gain: 21% (bull) / 25% (bear)
- Throwbacks occur ~50% of the time; hurt performance when they occur
- Gaps on breakout day improve performance significantly (43% avg with gap)
- Breakout above neckline: measure height of pattern (head to neckline),
  add to neckline = minimum price target.
- TALL patterns perform better than short patterns.
- Narrow patterns perform better than wide patterns.
- Best breakout position in yearly range: near yearly high = best performance.

HEAD AND SHOULDERS TOP (Reversal):
- Complement of HSB — mirror rules apply for short entries.
- Volume: left shoulder and head have highest volume; right shoulder: diminished.
- Failure: if price does not break neckline after right shoulder, pattern fails.
- Busted pattern (fails to drop 5%) = possible reversal to upside — trade the bust.

DOUBLE BOTTOM (Eve & Adam / Eve & Eve / Adam & Adam):
- Bullish reversal pattern. Confirmed on close above the peak between the two bottoms.
- Without confirmation, 65% chance price rises (but wait for close confirmation).
- Measure rule: height from bottom to confirmation peak, added to confirmation = target.
- Target achieved 72-79% of the time.
- If second bottom is higher (W-shape), stronger pattern.

DOUBLE TOP (Eve & Adam):
- Bearish reversal. Confirmed on close BELOW the lowest low between the two peaks.
- Average decline (bull market): ~15-16% | Bear market: ~23-25%
- Failure rate to drop 15%: 56% in bull market (low reliability in bull markets).
- STICK TO BEAR MARKET DOUBLE TOPS for better results.
- Light breakout volume actually performs BETTER than heavy (exception to normal rule).
- Pullbacks occur 64% of the time (bull) in ~11 days; hurt performance.
- Narrow AND tall double tops perform best.

ASCENDING TRIANGLE (Continuation/Reversal):
- Horizontal resistance + rising lows = bullish coil.
- Breakout almost always upward (breakout when resistance finally breaks).
- Measure: height of triangle (widest part) added to breakout point = target.
- 100% of triangle depth is common target on symmetric triangles (Duddella).
- False breakouts do occur; wait for close confirmation.
- Stop: below last swing low within the triangle.

DESCENDING TRIANGLE:
- Horizontal support + lower highs = bearish coil.
- Breakout almost always downward.
- Measure: height added/subtracted from breakout.

FLAGS (Continuation):
- Form after a strong impulse move (flagpole); consolidation in narrow parallel channel.
- Breakout in direction of original trend.
- Target: flagpole length added to breakout point.
- Volume: decreases during flag formation, surges on breakout.
- High-and-tight flag: very bullish; flagpole must be steep (>45% rise in <4 weeks).

WEDGES:
- Rising Wedge (bearish): price in upward-sloping converging channel.
  Typically breaks DOWN. Stop above upper trendline.
- Falling Wedge (bullish): price in downward-sloping converging channel.
  Typically breaks UP. Stop below lower trendline.

TRIANGLES — SYMMETRIC:
- Entry: wait for breakout above/below triangle, confirmed by close.
- Target: 100% of the maximum depth from breakout level (Duddella).
- Stop: below first major swing low below trendline (long) or above first major
  swing high (short).
- Trend continuation is the most common outcome.

RECTANGLE PATTERNS:
- Price bounces between horizontal support and resistance.
- Rectangle bottom = bullish continuation; rectangle top = bearish continuation.
- Entry: buy breakout above resistance or sell breakdown below support.
- Target: height of rectangle added to breakout.
- Stop: opposite side of rectangle.

DIAMOND TOP/BOTTOM:
- Forms with widening then narrowing price action (like a diamond on chart).
- Volume: diminishes over the length of the formation.
- Bearish with downward breakout; bullish with upward breakout.
- Similar to head-and-shoulders; treat as such for measure rule.

ROUNDING BOTTOM / SAUCER:
- Gradual U-shaped reversal. Long base = stronger move.
- Volume forms U-shape: high at edges, low in middle.
- Breakout: price clears the "rim" (resistance of the rounded top).
- Very reliable, but slow-developing.

### Gartley Harmonic Patterns (Gartley 1935, refined by Pesavento, Carney)
All harmonic patterns use XABCD structure with Fibonacci ratios.
Trades are entered at point D = Potential Reversal Zone (PRZ).

GARTLEY PATTERN (Bullish):
- X to A: initial impulse up
- A to B: retracement of 0.618 of XA (defining condition)
- B to C: 0.382 to 0.886 of AB
- C to D: PRZ at 0.618–0.786 of XA (measured from X), also 1.272–1.618 of BC
- Entry: one tick above high of confirmation bar at D (wide-range or higher-high bar)
- Stop: below X
- Targets: A level, then 1.272 and 1.618 of XA extension from D

GARTLEY PATTERN (Bearish):
- Mirror of bullish: enter one tick below low of confirmation bar at D
- Targets: A level, then below X

BAT PATTERN (Carney, 2001):
- B retracement must be LESS THAN 0.618 of XA (differentiates from Gartley)
- PRZ: 0.886 of XA, 1.272 of AB=CD, 1.618 of BC
- Stop: one tick below X (bullish) or above X (bearish)
- Targets: 1.272 of XA, then 1.618 of XA

BUTTERFLY PATTERN (Gilmore/Pesavento):
- B retracement at 0.786 of XA (key defining ratio)
- D extends BEYOND X: 1.272 of XA (usual), up to 1.618
- AB=CD in perfect form
- Occurs at major market tops and bottoms
- Stop: below D's low (bullish) or above D's high (bearish)
- Targets: 100% of AD and 162% of XA from D

CRAB PATTERN (Carney, 2000):
- B retracement: 0.382–0.618 of XA
- D extends to 1.618 of XA (most extreme extension)
- PRZ: 1.27 of AB, 1.618 of XA, 2.618–3.618 of BC
- Stop: below PRZ low (bullish) or above PRZ high (bearish)
- Targets: B level, C level, A level
- Notes: Crab PRZ is the most extreme extension; high-reward trades

ABC PATTERN (Gartley 1935 basic pattern):
- C retracement of 0.382–0.618 of AB
- D projection: 1.272–1.618 of BC, or 0.786–0.886 of AB
- Entry above previous bar's high (bullish) or below bar's low (bearish)
- Stop: below C (long) or above C (short)
- Targets: 100% of AB, then 127% of BC

### Lindsay 3 Peaks and a Domed House
Complex long-term pattern; takes 8-24 months to complete.
Three peaks at roughly the same level form over several months.
Then a "domed house" forms: a parabolic advance above peaks, followed by sharp decline.
The decline from the dome typically equals or exceeds the amplitude of the dome itself.
Identified by three notable local highs (peaks), each separated by at least one month.
After the third peak, price often rallies to form the dome before collapsing.

### Candlestick Reversal Patterns (Fischer)
HAMMER / HANGING MAN:
- Long lower shadow (3x the body length), small body near the top.
- Hammer at end of downtrend = bullish reversal.
- Hanging Man at end of uptrend = bearish reversal.
- Confirm: next bar must close above hammer high (bull) or below hanging man low (bear).

ENGULFING PATTERN:
- Bullish: large white body completely covers previous small black body (downtrend end).
- Bearish: large black body completely covers previous small white body (uptrend end).
- Strongest signal when the engulfing bar is much larger than the previous bar.

HARAMI (Inside Day):
- Small body fits completely within previous day's large body.
- Harami cross (doji inside) = even stronger warning of trend reversal.
- Valid at end of extended up or downtrend; stronger when small body color opposes trend.

DOJI:
- Open ≈ Close = indecision. Not actionable alone; must come at end of trend.
- After long uptrend + doji = potential top. Add engulfing for confirmation.
- After long downtrend + doji = potential bottom.

MORNING STAR (3-bar bullish reversal):
1. Large black body (downtrend continues)
2. Star: small body gapping below #1 (indecision)
3. Large white body covering ≥50% of bar #1
- Ideal: gap between star and bar #3.
- Strong reversal signal; more powerful if bar #3 is an engulfing pattern.

EVENING STAR (3-bar bearish reversal):
1. Large white body (uptrend continues)
2. Star: small body gapping above #1 (indecision)
3. Large black body covering ≥50% of bar #1
- The mirror of morning star.

PIERCING PATTERN / DARK CLOUD COVER:
- Piercing: bullish; second white bar covers >50% of previous black bar at end of downtrend.
- Dark Cloud: bearish; second black bar covers >50% of previous white bar at end of uptrend.
- Rule: "at least 50%" is the minimum; more coverage = stronger signal.

BELT-HOLD:
- Bullish belt-hold: opens at or near low, closes at or near high (large white body).
- Bearish belt-hold: opens at or near high, closes at or near low (large black body).
- If next day opens ABOVE a bearish belt-hold = false signal (price likely continues up).
- If next day opens BELOW a bullish belt-hold = false signal (price likely continues down).

---

## BILL WILLIAMS INDICATORS
Source: New Trading Dimensions (Bill Williams)

### The Alligator (3 Smoothed Moving Averages)
- Jaw (Blue): 13-period SMMA, offset 8 bars forward
- Teeth (Red): 8-period SMMA, offset 5 bars forward
- Lips (Green): 5-period SMMA, offset 3 bars forward
Alligator SLEEPING: Lines intertwined/converging = no trend, stay out.
Alligator AWAKENING: Lines starting to separate = trend forming.
Alligator EATING: Lines fully separated and fanning = strong trend in progress.
Alligator SATIATED: Lines converging after separation = trend ending; take profits.

CRITICAL RULE: Only trade OUTSIDE the Alligator's mouth.
- Buy fractal signals only when the fractal is ABOVE the Teeth (red, middle) line.
- Sell fractal signals only when the fractal is BELOW the Teeth line.
- "Do not feed the Alligator" = never trade into the mouth (against the teeth).

### Fractals (First Dimension)
Technical definition: minimum 5 consecutive bars where the middle bar's high is
the highest high (buy fractal) or its low is the lowest low (sell fractal).
The middle bar's extreme must be higher/lower than the 2 bars on each side.
Fractal is FORMED by the 5-bar pattern; is TRIGGERED when price hits the fractal level.
Entry: buy one tick ABOVE the high of the fractal bar (triggered entry).
Entry: sell one tick BELOW the low of the fractal bar.
Note: what matters is where the signal is HIT, not where it was FORMED.
First fractal outside the Alligator's mouth = initial trade signal.
After first fractal triggered, take ALL subsequent fractals in same direction.

### Awesome Oscillator (Second Dimension)
Formula: 5-period simple moving average of midpoints [(H+L)/2] MINUS
         34-period simple moving average of midpoints
Color: green bar = AO bar higher than previous bar; red bar = AO bar lower.

THREE BUY SIGNALS:
1. Saucer Buy (AO above zero): AO histogram goes down 2 bars (red), then up (green).
   Minimum 3 bars. All bars above zero line. Entry stop: one tick above bar #3's high.
2. Zero Cross Buy: AO crosses from negative to positive.
   Entry: one tick above high of bar that crosses zero. That bar will be green.
3. Twin Peaks Buy (AO below zero): two downward peaks below zero; second peak
   is HIGHER (less negative) than first. AO must NOT cross zero between peaks.
   Entry: one tick above high of trigger bar (green bar after second peak).

THREE SELL SIGNALS (mirror of buys):
1. Saucer Sell (AO below zero): 2 green bars then 1 red bar, all below zero.
2. Zero Cross Sell: AO crosses from positive to negative.
3. Twin Peaks Sell (AO above zero): two upward peaks; second is LOWER (less positive).

RULE: If a signal is generated but NOT HIT on that bar, and the next bar changes color,
the signal is CANCELED.

### Accelerator Oscillator (Third Dimension)
- AC = Awesome Oscillator - 5-period SMA of AO
- Color coded same as AO (green/red).
- BUY confirmation: need 2 consecutive green AC bars if above zero; 3 if below zero.
- SELL confirmation: need 2 consecutive red AC bars if below zero; 3 if above zero.
- AC changes BEFORE AO, which changes BEFORE price.
- Hierarchy: Volume → AC → AO → Price (each leads the next).

### Williams' Trading Hierarchy
Price is the LAST thing that changes. Momentum changes BEFORE price.
Volume changes BEFORE momentum. Market participant decisions change BEFORE volume.
Therefore: trade momentum, not just price. Use AO as the primary momentum tool.

---

## VOLUME ANALYSIS
Sources: Investing with Volume Analysis (Buff Dormeier), Wyckoff, Bill Williams

### Core Volume Principles (Newton's Laws Applied to Markets)
1. Law of Inertia: price cannot change without volume.
2. Law of Force: Force = Mass × Acceleration.
   Volume (force) moves price (mass) by a given amount (acceleration/momentum).
   If volume (force) increases while price change (acceleration) decreases = EXHAUSTION.
   "More effort, less result" = Wyckoff's Law of Effort vs. Result = trend dying.
3. Law of Supply and Demand: buying pressure (demand) > selling pressure (supply) = price rises.

### Volume Confirmation Rules
- High-volume movements CONFIRM the trend direction.
- Low-volume movements CONTRADICT the trend (likely to reverse or stall).
- Volume DECLINES during healthy consolidation (flags, pennants, triangles).
- Volume SPIKES at the onset of a new price trend (breakout bar).
- Volume should trend in the same direction as price.
- Volume DIVERGING from price = warning that trend may be ending.

### On-Balance Volume (OBV — Granville)
"Volume precedes price." Rising OBV while price is flat = accumulation; expect price rise.
Falling OBV while price is flat = distribution; expect price fall.
OBV making new highs while price makes new highs = confirmation of uptrend.
OBV FAILING to make new highs while price makes new highs = bearish divergence.
OBV making new lows confirms downtrend. OBV diverging up while price still falling = bullish.

### Volume/Price Confirmation Indicator (VPCI — Dormeier)
VPCI = difference between volume-weighted moving average and simple moving average.
Positive VPCI = money flowing INTO the stock (bullish).
Negative VPCI = money flowing OUT of the stock (bearish).
Best trades: bullish price trend + positive VPCI = double confirmation.
Worst: overbought price + negative VPCI = high failure risk.
The direction VPCI is MOVING matters as much as its absolute level.

### Four Phases of Volume Analysis
Phase 1 — ACCUMULATION: Low price, increasing volume quietly.
  Smart money buying. Price relatively flat; no public interest.
Phase 2 — MARKUP: Price rises with expanding volume.
  Public starts to notice. Trend firmly established.
Phase 3 — DISTRIBUTION: High price, high volume, but little net progress.
  Smart money selling to the public. Churn pattern.
Phase 4 — MARKDOWN: Price falls. Panic selling.
  Volume can be high at climax, then low as selling dries up.

### Anti-Volume Stop Loss (AVSL — Dormeier)
An objective, quantitative trailing stop loss that uses:
- Lower Bollinger Band of the security's lows (accounts for volatility)
- VPCI weighting (looser stop for strong volume, tighter for weak volume)
Formula: AVSL = Lower Bollinger Band(Price, Length, StdDev)
  Where Length = Round(3 + VPCI)
  StdDev = 2 × (VPCI × VM)
Key insight: a volatile stock gets a wider stop; a stable stock gets a tighter stop.
When VPCI is negative (weak volume), the stop TIGHTENS = more protective.
When VPCI is positive (strong volume), the stop LOOSENS = lets winners run.

### Volume Breakout Rules
- Breakout on volume > 200% of 30-day average = strong signal.
- Breakout on volume < 30-day average = weak breakout; higher failure risk.
- Volume spike at a KEY LEVEL (resistance, support, Fibonacci) = most significant.
- For head-and-shoulders bottom: breakout gap with volume = best performance (+43% avg).

### Market Breadth + Volume Positioning System (Dormeier MPS)
Best bull condition: advance-decline UP + cap-weighted up volume rising = upper-left quadrant.
Best bear condition: advance-decline DOWN + cap-weighted down volume rising = lower-right.
Out of sync = intermediate state. Direction of movement on the quadrant map matters most.
NW movement (toward upper-left) = bullish. SE movement (toward lower-right) = bearish.

---

## RISK MANAGEMENT RULES
Synthesized from Wyckoff, Gann, Fischer, Williams

### Position Sizing
- NEVER risk more than 2% of total trading capital on any single trade.
- After 3 consecutive losses that reduce capital by >25%, reduce position size by 50%.
- Pyramid only when in PROFIT. Add to winners, not losers.
- Pyramid rule (Gann): add equal unit every 5% (or equivalent) in your favor,
  as long as trend indicator confirms. Stop for ALL positions = 1 unit below last trend low.

### Stop Loss Placement
- Wyckoff: stop goes just beyond the last meaningful support/resistance identified on chart.
- Gann: stop 1-3 points (or pips/ticks) beyond Trend Line extreme.
  In very active markets: 3-point stops. Slow markets: 1-point stops.
  After big profits: can use 5-point stops, but only after large gains.
- Pattern-based: stop beyond the PATTERN LOW or HIGH.
  Gartley/Bat/Butterfly: stop beyond X (the origin point of the pattern).
  Double top/bottom: stop beyond the second peak/trough.
  Head and shoulders: stop just above the right shoulder high (for shorts).

### Profit-to-Risk Requirements
- Wyckoff standard: MINIMUM 3:1 reward-to-risk before entering ANY trade.
- Preferred: 5:1 or greater for the initial target.
- If pattern has poor R/R, skip the trade regardless of signal strength.

### Stop-Loss Discipline
- Place stops BEFORE entry; never move a stop AGAINST you (only in your favor).
- Protect profits: after a 10-15% gain, raise stop to breakeven.
- Do not let a 10% winner become a 10% loser.
- Compounding mathematics: losing 25% requires 35% gain to recover;
  losing 50% requires 100% gain to recover.
- "The best mistakes are the realized ones." — cut losses quickly.
- Never add to a losing position.

### Trade Management
- When market moves 50% of target, take partial profits or tighten stop.
- Trail stop after strong move using daily bar lows (bull) or highs (bear).
- In fast markets: tight trailing stops (1-2 bars). In slow markets: looser trailing.
- Exit immediately if market action contradicts your reason for entry.

---

## MARKET CYCLES & TIMING
Sources: Gann, Gann Masters I & II, Astrology-adjacent timing concepts

### Gann Time Cycles (Key Periods)
- Daily: 3, 5, 7, 10, 12, 15, 18, 21, 24, 30 days
- Weekly: 3, 5, 7, 13, 26, 52 weeks
- Calendar: 45, 60, 90, 120, 144, 180, 270, 360 calendar days
- Monthly: 3, 4, 6, 12, 18, 24, 36, 48, 60, 72, 84, 120 months
- Natural squares: 16, 25, 36, 49, 64, 81, 100, 121, 144, 169, 196, 225
- 360-degree cycle: key multiples are 45, 90, 135, 180, 270, 360

### Time Analysis Rules
1. Price and Time Squaring: when the NUMBER OF DAYS from a significant high or low
   equals the PRICE of that high or low, price and time are "in square" = turning point.
   Example: 53 days from a low of $53 = price and time squared = watch for reversal.
2. When reaction time EXCEEDS previous reaction time = trend has changed.
3. When a market has had 3 or fewer days of reaction, trend is very strong (Gann).
4. Fibonacci time counts: 3, 5, 8, 13, 21, 34 bars from a high/low are natural pivots.
5. Watch for cluster of time counts (Fibonacci + Gann + cycle) at same bar = strong pivot.

### Seasonal / Calendar Tendencies
- January effect: direction in first 3-7 days often sets tone for 3-4 months.
- July: mid-year inflection; first 3-7 days matter.
- End-of-quarter rebalancing: watch for volatility.
- Elliott Wave time relationships: waves 1 and 5 are often equal in time;
  wave 3 tends to extend; corrections (2, 4) are often related by 0.618 in time.

### Elliott Wave Timing Interactions
- In 5-wave impulse: waves 1, 3, 5 are impulse; waves 2, 4 are corrections.
- Common relationships: wave 3 = 1.618 × wave 1; wave 5 = wave 1 (equality) or
  0.618 × sum of waves 1 and 3.
- Wave 2 corrects 50-78.6% of wave 1; wave 4 corrects 38.2% of wave 3.
- When wave 4 ends near the top of wave 1 (former resistance, now support) = classic buy.
- Extended wave 3 = most common extension. A 3rd wave extension targets 2.618 × wave 1.

---

## ENTRY RULES (Synthesized Best Practices)

### Setup Requirements (All conditions should align)
1. TREND CONTEXT: Identify the primary trend (daily chart), intermediate trend (4h),
   and short-term trend (1h or 15m). Trade with at least 2 of the 3 timeframes aligned.
2. PATTERN: Identify a specific, named pattern with clear structure.
   The pattern must be complete or at the PRZ (Potential Reversal Zone).
3. SUPPORT/RESISTANCE: Pattern completes at a key S/R level, Fibonacci confluence,
   Gann level, or prior high/low.
4. VOLUME CONFIRMATION: Volume behavior must confirm the setup:
   - Bull setup: volume declining on the pullback to entry = healthy correction.
   - Bear setup: volume declining on the rally to entry = weak bounce.
5. INDICATOR ALIGNMENT (optional but strengthening):
   - RSI: oversold (<30) for longs; overbought (>70) for shorts (or divergence).
   - ADX > 25 = trend is strong enough to trade; < 20 = avoid trend trades.
   - AO: Twin Peaks or Zero Cross in the direction of trade.
   - Williams Alligator: price outside the Alligator's mouth in direction of trade.
6. RISK/REWARD: Minimum 3:1 R/R confirmed before entry.

### Specific Entry Triggers
- FRACTAL: enter one tick above/below the fractal bar's high/low (Williams).
- PATTERN BREAKOUT: enter on the close above/below the pattern's key level.
  Do not anticipate. Wait for confirmation.
- HARMONIC PATTERN at PRZ: enter when a confirmation bar (wide range, engulfing,
  morning/evening star) completes at the D level.
- WYCKOFF SPRING: buy the first bar that closes ABOVE the level that was broken
  in the shakeout, with volume dropping off.
- DOUBLE/TRIPLE BOTTOM/TOP (Gann): enter on 1-3 tick break above/below the
  confirmation level, with stop 1-3 ticks on the other side of the pattern extreme.

---

## EXIT RULES (Synthesized Best Practices)

### Profit Taking
1. MEASURED MOVE TARGETS:
   - Head and shoulders: add pattern height to neckline breakout.
   - Triangles/flags/rectangles: add pattern height to breakout.
   - Harmonic patterns: first target = A level; second = 1.272 or 1.618 of XA.
   - Fibonacci extension: 1.272, 1.618 of initial swing from breakout.
2. PARTIAL EXIT: take 50% of position at first target (A level, 1.272 extension,
   or measured move). Move stop to breakeven. Let remaining half run.
3. TRAIL STOP after first target: use Alligator Teeth line (Williams) OR
   daily bar lows/highs (Gann trailing stop rule OR AVSL method).

### Exit Signals (Mandatory Exits)
- Price closes BELOW Alligator Teeth (in a long trade) = Alligator awakening to new direction.
- Three consecutive bars FAILING to make new highs/lows in a trend = momentum loss.
- Bearish/bullish engulfing at a target level = sharp reversal warning.
- Evening star or morning star at target level.
- OBV/VPCI diverges from price at target = distribution/accumulation signal.
- Volume spike with no further price progress = effort without result = Wyckoff exhaustion.
- ADX starts declining from above 40 = trend exhaustion; tighten stops.
- Time cycle completion at a Fibonacci or Gann level = close trade, wait for new setup.

### Failure Signals (Stop Out Immediately)
- Price breaks back BELOW the neckline of a head-and-shoulders bottom (failed breakout).
- Harmonic pattern: price closes BEYOND X level (pattern invalidated).
- Double bottom: price closes BELOW the second low (pattern failed).
- Breakout bar closes back INSIDE the range it broke from (false breakout).
- Volume SURGES against your position at a key level = large player taking the other side.

---

## REGIME-SPECIFIC TACTICS

### STRONG TREND (ADX > 30, directional)
- Trade ONLY with the trend. No counter-trend entries.
- Use shallow pullbacks (38.2% retracement) as entries; deeper retracements are rare.
- Prioritize Wyckoff Buying/Selling Test criteria.
- Use AO Zero Cross or Saucer signals in trend direction only.
- Pyramid aggressively on confirmations; trail stops at recent 2-3 bar extremes.
- Do NOT use oscillators (RSI, stochastics) as reversal signals in strong trends;
  they will stay overbought/oversold for extended periods.

### RANGING / SIDEWAYS MARKET (ADX < 20)
- Trade mean-reversion. Buy at support, sell at resistance within the range.
- Gann rule: buy double/triple bottoms, sell double/triple tops.
- Use oscillators (RSI, stochastics) — they work well in ranging markets.
- Take profits at the opposite side of the range; don't expect breakouts.
- Watch for increasing volume at range extremes = potential breakout coming.
- Pattern alert: long sideways ranges = when price breaks out with gap + volume,
  expect a MAJOR trend change (Gann).

### WEAK/BEAR TREND (ADX > 25, price below key MAs)
- Short only; avoid longs except at major support with strong Wyckoff reversal signals.
- Look for Wyckoff Selling Tests, bearish harmonic completions, H&S tops.
- Rally-sell setups: wait for price to rally 38.2-61.8% on declining volume,
  then enter short with stop above the most recent high.
- Downside targets: Fibonacci extensions (1.272, 1.618) from the breakdown.
- Bear market: head-and-shoulders tops, double tops, rising wedges are highest probability.
- Bulkowski: H&S top average decline 35%; double top average 15% (bull), 24% (bear).

### NEAR 52-WEEK HIGH (Breakout conditions)
- Gann rule: when price breaks into ALL-TIME or 52-WEEK highs, there is NO overhead
  resistance. Market is in its strongest position. BUY with the trend.
- Wait for a 1-3 day pullback to the breakout level; enter if pullback volume is light.
- Widening of Alligator mouth to the upside + AO above zero = strong momentum.
- Volume MUST confirm: breakout bar volume should exceed 30-day average by 50%+.
- Fibonacci: project 1.272 and 1.618 of the base's range as targets.

### NEAR 52-WEEK LOW (Potential accumulation or continuation down)
- Two scenarios: (a) Wyckoff accumulation base forming = buyer; (b) mark-down = seller.
- Determine which by volume: shrinking volume at new lows = (a); surging volume = (b).
- For potential long: wait for Wyckoff Spring or Selling Climax, then Buying Tests.
- For short continuation: sell any rally to resistance (supply level) on declining volume.
- Key rule: if price makes a new low and volume is LOWER than previous lows,
  selling pressure is drying up = potential bottom forming (Wyckoff).

### HIGH VOLUME BREAKOUT
- Volume ratio > 2.0 (200% of average): strong conviction.
- Enter on the first pullback after the breakout if volume declines on pullback.
- Stop: below the breakout bar's low (or high for short).
- If volume stays high after breakout, the move is extended and sustainable.
- Wyckoff: a breakout on low volume is suspect; wait for retest or volume surge.

### LOW VOLUME / RSI DIVERGENCE (Reversal watch)
- Volume declining while price makes new highs/lows = classic divergence.
- RSI divergence (price makes new high but RSI does not) = momentum fading.
- Wait for a catalyst: engulfing candle, Wyckoff spring/upthrust, harmonic completion.
- Enter ONLY after confirmation. Divergences can persist; don't fight the tape.
- Constance Brown rule: use oscillators AT a Fibonacci or Gann level to confirm;
  divergence + key level = high-probability reversal setup.

---

## KEY NUMERIC THRESHOLDS AND RATIOS (Quick Reference)

Fibonacci Retracements: 23.6%, 38.2%, 50%, 61.8%, 78.6%, 88.6%
Fibonacci Extensions: 100%, 127.2%, 161.8%, 200%, 261.8%, 361.8%
Gann Key Levels: 25% (1/4), 33.3% (1/3), 50% (1/2), 66.7% (2/3), 75% (3/4)
Gann Angles: 8x1, 4x1, 3x1, 2x1, 1x1, 1x2, 1x3, 1x4, 1x8
Gann Time: 45, 90, 120, 144, 180, 270, 360 days; 3, 5, 7, 13, 26, 52 weeks
Wyckoff Minimum R/R: 3:1 (ideal: 5:1)
Williams AO: 5-period vs. 34-period SMA of midpoints
Williams Alligator: Jaw=13/8, Teeth=8/5, Lips=5/3 (period/offset)
Bulkowski HSB avg rise: 38% (bull), 30% (bear)
Bulkowski Double Top avg fall: 15% (bull), 24% (bear)
Volume breakout confirmation: >150% of 30-day avg = strong; >200% = very strong
Minimum holding period at Fibonacci level for confirmation: 1-3 bars close
ADX thresholds: <20 = no trend; 20-25 = weak; 25-40 = moderate; >40 = strong trend

================================================================================
END OF TRADER BRAIN KNOWLEDGE BASE
================================================================================
"""


def get_brain_context(
    regime: str,
    direction: str,
    rsi: float,
    adx: float,
    volume_ratio: float,
    near_52w_high: bool
) -> str:
    """
    Return a targeted subset of the TRADER_BRAIN knowledge base based on
    current market conditions.

    Parameters
    ----------
    regime : str
        Market regime string. Expected values: 'trend_up', 'trend_down',
        'ranging', 'breakout_up', 'breakout_down', 'reversal_up', 'reversal_down'
    direction : str
        Proposed trade direction: 'long' or 'short'
    rsi : float
        Current RSI value (0-100)
    adx : float
        Current ADX value (0-100)
    volume_ratio : float
        Current volume as a ratio of the 30-day average (e.g. 1.5 = 150% of avg)
    near_52w_high : bool
        Whether price is within 5% of the 52-week high

    Returns
    -------
    str
        A focused, trimmed version of the knowledge base relevant to the
        current conditions, suitable for passing to an AI as context.
    """

    sections = []

    # Always include core principles
    sections.append(_extract_section("## WYCKOFF METHOD"))
    sections.append(_extract_section("## FIBONACCI LEVELS"))
    sections.append(_extract_section("## RISK MANAGEMENT RULES"))

    # Regime-specific sections
    regime_lower = regime.lower() if regime else ""
    direction_lower = direction.lower() if direction else ""

    if "trend" in regime_lower or adx > 25:
        sections.append(_extract_section("## GANN PRINCIPLES"))
        sections.append(_extract_section("## MARKET CYCLES & TIMING"))

    if "breakout" in regime_lower or (volume_ratio > 1.5):
        sections.append(_extract_section("## VOLUME ANALYSIS"))

    if "reversal" in regime_lower or rsi < 30 or rsi > 70:
        sections.append(_extract_section("## CHART PATTERNS"))
        sections.append(_extract_section("## BILL WILLIAMS INDICATORS"))

    sections.append(_extract_section("## ENTRY RULES"))
    sections.append(_extract_section("## EXIT RULES"))

    # Regime-specific tactics block
    regime_tactics = _get_regime_tactics(regime_lower, direction_lower, rsi, adx, volume_ratio, near_52w_high)
    sections.append(regime_tactics)

    combined = "\n\n".join(s for s in sections if s.strip())
    return combined


def _extract_section(header: str) -> str:
    """Extract a named section from TRADER_BRAIN."""
    lines = TRADER_BRAIN.split("\n")
    in_section = False
    result_lines = []
    for line in lines:
        if line.strip().startswith(header.strip()):
            in_section = True
            result_lines.append(line)
            continue
        if in_section:
            # Stop at next ## section header (but not sub-headers)
            if line.startswith("## ") and not line.strip().startswith(header.strip()):
                break
            result_lines.append(line)
    return "\n".join(result_lines)


def _get_regime_tactics(regime: str, direction: str, rsi: float, adx: float,
                        volume_ratio: float, near_52w_high: bool) -> str:
    """Build a focused tactical context block for the current conditions."""
    tactics = ["## APPLICABLE REGIME TACTICS\n"]

    if adx > 30 or "trend" in regime:
        tactics.append(_extract_subsection("### STRONG TREND"))

    if adx < 20 or "rang" in regime:
        tactics.append(_extract_subsection("### RANGING / SIDEWAYS MARKET"))

    if "trend_down" in regime or (direction == "short" and adx > 25):
        tactics.append(_extract_subsection("### WEAK/BEAR TREND"))

    if near_52w_high or "breakout_up" in regime:
        tactics.append(_extract_subsection("### NEAR 52-WEEK HIGH"))

    if not near_52w_high and ("breakout_down" in regime or rsi < 25):
        tactics.append(_extract_subsection("### NEAR 52-WEEK LOW"))

    if volume_ratio > 1.5 or "breakout" in regime:
        tactics.append(_extract_subsection("### HIGH VOLUME BREAKOUT"))

    if volume_ratio < 0.8 or rsi > 65 or rsi < 35:
        tactics.append(_extract_subsection("### LOW VOLUME / RSI DIVERGENCE"))

    # Always include the quick reference numbers
    tactics.append(_extract_subsection("## KEY NUMERIC THRESHOLDS"))

    return "\n\n".join(t for t in tactics if t.strip())


def _extract_subsection(header: str) -> str:
    """Extract a subsection (###) from TRADER_BRAIN."""
    lines = TRADER_BRAIN.split("\n")
    in_section = False
    result_lines = []
    header_stripped = header.strip()
    for line in lines:
        if line.strip().startswith(header_stripped):
            in_section = True
            result_lines.append(line)
            continue
        if in_section:
            # Stop at same or higher level header
            if (line.startswith("## ") or line.startswith("### ")) and \
               not line.strip().startswith(header_stripped):
                break
            result_lines.append(line)
    return "\n".join(result_lines)


if __name__ == "__main__":
    # Quick demo
    print("TRADER_BRAIN loaded. Total characters:", len(TRADER_BRAIN))
    print("\n--- SAMPLE CONTEXT (trend_up, long, RSI=55, ADX=35, vol=1.8x, near 52w high) ---")
    ctx = get_brain_context(
        regime="trend_up",
        direction="long",
        rsi=55.0,
        adx=35.0,
        volume_ratio=1.8,
        near_52w_high=True
    )
    print(ctx[:3000])
    print(f"\n[...total context length: {len(ctx)} chars]")
