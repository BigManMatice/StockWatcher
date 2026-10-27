# StockWatcher: development plan

The priority is to make the existing program reliable before adding more prediction features. First, we need to prove that the data is correct, the current analysis runs consistently, and the program measures its accuracy honestly. Only then should we build a simple prediction based on historical results.

The goal is not to make the bot produce more warnings. It is to make its existing warnings measurable, testable, and useful.

## The development roadmap

## Phase 1 — Make the base program work

First priority

Fix crashes, data problems, database issues, and repeated processing. Verify that the existing features work before changing the strategy.

## Phase 2 — Measure current accuracy

Test existing BUY/SELL warnings against subsequent market prices. Separate completed evaluations from pending or invalid ones.

## Phase 3 — Build one simple predictor

Use the measured historical success rate to estimate the chance of a clearly defined outcome. Start with a simple baseline, not a complex AI model.

## Phase 4 — Test whether it actually improves results

Compare the predictor against the baseline using data it has never seen. Keep it only if the improvement is measurable.

## Phase 5 — Improve the strategy

Only after the earlier phases pass: test better signals, additional features, risk/reward calculations, and eventually machine learning.

## Phase 1 — Make the existing program reliable

Do not add any new indicators, prediction models, or features yet. Work through the current code in this order.

### Step 1.1 — Establish a working baseline

Before changing anything:

- Make a backup or create a Git commit of the current working version.
- Install the project's dependencies in a clean environment.
- Run the application using its normal startup command.
- Check that the watchlist loads, market data is retrieved, analysis completes, alerts are generated when appropriate, and the database is updated.
- Record existing errors and warnings.

Deliverable: a reproducible baseline, including the current startup command, dependencies, and known failures.

### Step 1.2 — Fix the data pipeline

This is the highest-priority technical task. A prediction is worthless if the underlying prices are wrong.

| Check             | What to do                                                                                                            |
| ----------------- | --------------------------------------------------------------------------------------------------------------------- |
| Historical prices | Confirm dates, OHLCV columns, missing values and duplicate rows.                                                      |
| Live quotes       | Prevent a live quote from overwriting a historical daily OHLCV record with missing open, high, low and volume values. |
| Currency          | Verify that historical prices, entry prices, ATR and target prices use the same currency.                             |
| Market dates      | Handle weekends, market holidays and incomplete daily candles correctly.                                              |
| API failures      | Handle timeouts, rate limits, missing quotes and malformed responses without crashing the program.                    |

Your current `data.py` and `tracker.py` deserve particular attention here. The live-quote database write and the way unresolved alerts are repeatedly evaluated are two issues to investigate and test first.

Acceptance criteria: the same stored historical data produces consistent results, missing data is handled explicitly, and a failed API request does not corrupt records or stop the scanner.

### Step 1.3 — Make the tracker reliable

The tracker must distinguish between an alert that has not been evaluated yet and an alert that cannot be evaluated.

Implement and verify:

- Stable alert identifiers and consistent signal categories.
- A recorded entry price and timestamp.
- Clearly defined evaluation horizons, such as 1, 3 and 5 trading days.
- **Peak duration & holding period tracking:** Record the number of trading days until the maximum favorable excursion (peak return) is reached before a trend reversal or dip occurs, storing this in the database to support future supervised machine learning models.
- An evaluation status such as `pending`, `completed`, or `unscorable`.
- Protection against evaluating the same outcome repeatedly.
- Efficient data refreshes: fetch historical prices once per ticker per evaluation run, rather than once per alert.
- Logging for missing prices, unavailable ATR and other failed evaluations.

Do not count a pending alert as a failure. Do not silently exclude unscorable alerts without reporting how many there are.

### Step 1.4 — Test the base program

Create automated tests for the important existing functions before modifying their behaviour.

| Area         | Minimum tests                                                              |
| ------------ | -------------------------------------------------------------------------- |
| `data.py`    | Missing data, malformed responses, currency conversion and database writes |
| `signals.py` | Known indicator inputs, missing values, BUY/SELL/HOLD decisions            |
| `tracker.py` | Entry recording, outcome calculation, duplicate processing and statistics  |
| `bot.py`     | Startup, scanning, error handling and alert integration                    |

Run the tests after each change. Also perform one end-to-end test using a small watchlist and saved market data, so that API problems do not make every test dependent on the internet.

Phase 1 is complete when: the program starts reliably, the existing workflow completes, database records remain consistent, and automated tests pass. Do not redesign the strategy during this phase.

## Phase 2 — Find out how accurate the existing signals are

This is the first real analysis task. Measure the current system before attempting to improve it.

### Step 2.1 — Define what a correct prediction means

A percentage is meaningless until the outcome is defined.

For a first version, use the following simple definition:

- BUY: the price is higher at the end of the chosen evaluation period.
- SELL: the price is lower at the end of that period.
- HOLD: track separately; do not treat it as a BUY or SELL prediction.
- No valid outcome: leave it unscored and report why.
- **Peak duration metric:** Track the trading days elapsed from alert execution until the peak price movement (Maximum Favorable Excursion) before a dip.

Start with a one-trading-day horizon, then evaluate three- and five-trading-day horizons separately.

Your current tracker also uses an ATR-based threshold to determine whether a signal succeeded. That is a different metric. Keep it separate rather than mixing it into directional accuracy.

For example, a BUY signal that moves up slightly may be directionally correct but may fail your ATR-based success criterion.

### Step 2.2 — Calculate honest metrics

The initial report should contain:

- Directional accuracy: percentage of scored BUY/SELL signals whose predicted direction was correct.
- BUY accuracy: percentage of BUY signals that went up.
- SELL accuracy: percentage of SELL signals that went down.
- Coverage: percentage of generated signals that could be scored.
- Sample size: number of completed predictions.
- Average price return: average percentage return after the signal, with BUY and SELL handled consistently.
- ATR-threshold success rate: the existing stricter outcome metric, reported separately.
- **Average optimal holding duration:** The mean number of trading days required for trades to reach their peak return.

For directional accuracy:

\\[ \text{Accuracy} = \frac{\text{Correct predictions}}{\text{Scored predictions}} \times 100 \\]

Suppose the program generates 100 signals, 80 have valid outcomes, and 46 are correct.

\\[ \text{Accuracy} = \frac{46}{80}\times100 = 57.5\\% \\]

The result is 57.5% accuracy on 80 scored predictions, not 46% and not 57.5% of all generated alerts. The 20 unscored signals should be reported separately.

### Step 2.3 — Remove misleading estimates

Your current `signals.py` derives a value called `win_rate` from RSI. That does not establish a real historical success probability.

Until the tracker has enough reliable observations, display something such as:

> Historical accuracy: insufficient data

Once data is available, calculate actual historical rates from completed outcomes. Avoid labelling those rates as guaranteed probabilities of future success.

### Step 2.4 — Build an accuracy report

The report should show the results by signal type and evaluation horizon.

| Signal type | Horizon        | Correct | Scored | Accuracy | Avg. Peak Days |
| ----------- | -------------- | ------- | ------ | -------- | -------------- |
| BUY         | 1 trading day  | —       | —      | —        | —              |
| SELL        | 1 trading day  | —       | —      | —        | —              |
| BUY         | 3 trading days | —       | —      | —        | —              |
| SELL        | 3 trading days | —       | —      | —        | —              |
| BUY         | 5 trading days | —       | —      | —        | —              |
| SELL        | 5 trading days | —       | —      | —        | —              |

The dashes are intentional: the results must come from real evaluated alerts, not estimates.

Use stable categories such as `Bollinger Squeeze` or `Testing Resistance` rather than full formatted warning messages as the database's signal type. Otherwise, grouping and comparison become unreliable.

Phase 2 is complete when: you can run the program and answer, with actual data, how often each type of signal has been correct and how many observations support that result.

## Phase 3 — Create the first simple predictor

Only start this after Phases 1 and 2 pass.

The first predictor should be deliberately simple. It should answer one question:

Given a new BUY or SELL signal, what percentage of comparable historical signals succeeded over the same evaluation horizon?

### Step 3.1 — Start with a historical baseline

For example, suppose that over a five-trading-day horizon, 60 out of 100 comparable historical BUY signals were directionally correct.

The baseline historical success rate is 60%.

That is the starting estimate, not a guarantee that the next signal has a 60% chance of success. The result may change with the market, ticker, sample size and signal conditions.

### Step 3.2 — Add a simple confidence calculation

For the first version, calculate historical success rates by:

1. Signal direction: BUY or SELL.
2. Signal category.
3. Evaluation horizon.
4. Optionally, ticker or market regime, but only when there are enough observations.

Avoid creating many tiny groups. A rate based on five observations is much less reliable than a rate based on hundreds.

Display the estimate together with the sample size. If the sample is too small, return `Insufficient data` rather than inventing a percentage.

### Step 3.3 — Keep prediction separate from signal generation

Do not initially change how `signals.py` decides to issue BUY or SELL warnings.

Instead, add a small, independent analysis layer that reads the existing signal and the historical tracker results. This lets you compare the new estimate with the old system without changing its behaviour.

A first alert could look like this:

```
Ticker: EXAMPLE
Signal: BUY
Evaluation horizon: 5 trading days
Estimated holding period to peak: ~4 trading days

Historical directional accuracy: 60%
Completed comparable signals: 100
Status: Historical estimate, not a guarantee
```

The figures above are illustrative, not measured results from your program.

## Phase 4 — Check whether the predictor is genuinely useful

A historical accuracy rate alone does not prove that the system has predictive value.

### Step 4.1 — Compare against a baseline

Compare your signals against a simple benchmark, such as predicting the majority direction or using the historical market direction over the same period.

If the predictor has 55% accuracy but a basic benchmark achieves 57%, the predictor has not demonstrated an improvement.

### Step 4.2 — Avoid data leakage

Use earlier observations to calculate the historical estimate, then evaluate it on later observations that were not used to calculate it.

For example:

- Earlier period: build the historical baseline.
- Later period: test the baseline without updating it using future outcomes.
- After the test: compare the results.

For a more realistic ongoing test, use a walk-forward approach: update the historical information only as each new observation becomes available.

### Step 4.3 — Measure more than accuracy

A strategy can be directionally accurate and still lose money because losses are larger than gains.

After directional accuracy works, measure:

- Average return per signal.
- Gains versus losses.
- Maximum drawdown.
- Transaction costs and spread, where relevant.
- Results by ticker, signal category and market regime.

Do not optimise these metrics until the underlying evaluation process is trustworthy.

## Phase 5 — Improve the existing strategy

Only after the baseline has been measured and the first predictor has been tested should you consider new predictive features.

A sensible order is:

1. Remove signals that consistently perform poorly.
2. Investigate why successful and unsuccessful signals differ.
3. Test whether existing indicators add useful information individually.
4. Add directional confirmation to signals such as Bollinger squeezes.
5. Validate stop-loss, target and risk/reward calculations against historical data.
6. Compare each change with the previous version using the same test procedure.
7. Consider regression or classification models only when the simpler approach has reached a clear limitation.

Your Howest material on data exploration and regression can help with feature analysis, train/test splits and model evaluation. It does not, by itself, establish that a particular indicator predicts stock prices.

---

## Implementation checklist

- [ ] Back up the current working code and establish the baseline *(Phase 1)*
- [ ] Audit `data.py` and fix price/database consistency *(Phase 1)*
- [ ] Fix tracker evaluation, prevent redundant loops, and implement peak-duration / holding-period logging *(Phase 1)*
- [ ] Add and run tests for data, signals and tracker *(Phase 1)*
- [ ] Define directional success rules, horizons, and peak-tracking metrics *(Phase 2)*
- [ ] Generate a real historical accuracy and holding-duration report *(Phase 2)*
- [ ] Add the historical-rate baseline predictor *(Phase 3)*
- [ ] Run a later-period test against a benchmark *(Phase 4)*