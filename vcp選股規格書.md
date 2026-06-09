# VCP 選股規格書

## 1. 目的

本規格書定義 VCP（Volatility Contraction Pattern，價格波動收縮型態）的選股邏輯，用於從股票資料中篩選出「處於第二階段上升趨勢、價格波動逐步收縮、整理時間逐步壓縮」的候選股票。

VCP 篩選結果僅代表「候選股」，不代表立即買進。實際進場需等待股價放量突破樞紐點。

## 2. 型態定義

VCP 是強勢股在上升趨勢中出現的整理型態。其核心特徵如下：

- 股票已進入第二階段上升趨勢。
- 整理期間每次回檔幅度逐漸縮小。
- 理想狀態下，每次回檔約為前一次回檔的一半。
- 整理時間逐漸縮短，代表籌碼越來越穩定。
- 越接近突破點，成交量通常越萎縮。
- 放量突破壓力區或樞紐點後，型態才算完成。

## 3. 輸入資料需求

每日行情資料至少需包含：

| 欄位 | 說明 |
|---|---|
| date | 交易日期 |
| symbol | 股票代號 |
| open | 開盤價 |
| high | 最高價 |
| low | 最低價 |
| close | 收盤價 |
| volume | 成交量 |

建議額外計算：

| 指標 | 說明 |
|---|---|
| MA50 | 50 日移動平均線 |
| MA150 | 150 日移動平均線 |
| MA200 | 200 日移動平均線 |
| volume_MA10 | 10 日成交量均量 |
| volume_MA50 | 50 日成交量均量 |
| high_52w | 近 52 週最高價 |
| low_52w | 近 52 週最低價 |

## 4. VCP 三大選股條件

### 4.1 條件 1：股票處於第二階段上升趨勢

第二階段上升趨勢代表股票已脫離長期下降或底部整理，進入主升段。此條件用於先排除弱勢股。

#### 必要條件

| 編號 | 條件 | 說明 |
|---|---|---|
| T1 | close > MA200 | 股價高於長期均線 |
| T2 | MA150 > MA200 | 中期趨勢強於長期趨勢 |
| T3 | MA50 > MA150 | 短期趨勢強於中期趨勢 |
| T4 | MA200 最近 20 至 60 日走升 | 長期趨勢不能仍在下降 |

#### 建議條件

| 編號 | 條件 | 說明 |
|---|---|---|
| T5 | close > MA50 | 股價維持在短期均線之上 |
| T6 | 近 120 日漲幅 > 30% | 具備強勢股特徵 |
| T7 | close 距離 52 週高點 < 25% | 股價接近高位區 |
| T8 | close 高於 52 週低點至少 30% | 已明顯脫離低檔 |

#### 第二階段判斷公式

```text
stage2 =
  close > MA200
  and MA150 > MA200
  and MA50 > MA150
  and MA200_today > MA200_30_days_ago
```

嚴格版可加入：

```text
stage2_strict =
  stage2
  and close > MA50
  and close / close_120_days_ago - 1 > 0.30
  and close >= high_52w * 0.75
  and close >= low_52w * 1.30
```

## 5. 條件 2：價格波動呈現收縮

VCP 的核心是每次回檔幅度逐漸縮小。理想狀態下，後一次回檔約為前一次的一半。

### 5.1 波段偵測

需先找出整理區內的 swing high 與 swing low。

建議參數：

| 參數 | 建議值 | 說明 |
|---|---:|---|
| lookback_days | 40 至 80 | VCP 整理觀察區間 |
| swing_window | 3 至 5 | 判斷波段高低點的左右 K 數 |
| min_contractions | 2 | 至少需要 2 次收縮 |
| ideal_contractions | 3 至 4 | 理想收縮次數 |

### 5.2 回檔幅度計算

每一次 contraction 由一個 swing high 到後續 swing low 組成。

```text
drawdown_pct = (swing_high - swing_low) / swing_high
```

範例：

```text
第 1 次回檔：100 -> 80，回檔 20%
第 2 次回檔：98 -> 88，回檔 10%
第 3 次回檔：96 -> 91，回檔 5%
```

符合 VCP 收縮：

```text
20% > 10% > 5%
```

### 5.3 回檔收縮規則

寬鬆版：

```text
drawdown_2 < drawdown_1
drawdown_3 < drawdown_2
```

標準版：

```text
drawdown_2 <= drawdown_1 * 0.65
drawdown_3 <= drawdown_2 * 0.65
```

嚴格版：

```text
drawdown_2 <= drawdown_1 * 0.55
drawdown_3 <= drawdown_2 * 0.55
```

若只偵測到 2 次收縮，至少需符合：

```text
drawdown_2 <= drawdown_1 * 0.65
```

### 5.4 最後一次收縮

最後一次回檔越小越佳。

```text
last_drawdown <= 0.10
```

較嚴格可設定：

```text
last_drawdown <= 0.08
```

## 6. 條件 3：時間壓縮

時間壓縮代表每次回檔或整理所需時間越來越短，顯示賣壓釋放速度下降，籌碼逐漸穩定。

### 6.1 時間長度計算

每次 contraction 的時間長度：

```text
duration_days = swing_low_date - swing_high_date
```

或計算一段完整整理波：

```text
cycle_days = next_swing_high_date - current_swing_high_date
```

### 6.2 時間壓縮規則

寬鬆版：

```text
duration_2 <= duration_1
duration_3 <= duration_2
```

標準版：

```text
duration_2 <= duration_1 * 0.75
duration_3 <= duration_2 * 0.75
```

嚴格版：

```text
duration_2 <= duration_1 * 0.60
duration_3 <= duration_2 * 0.60
```

範例：

```text
第 1 次整理：20 天
第 2 次整理：10 天
第 3 次整理：5 天
```

符合時間壓縮。

## 7. 成交量輔助條件

成交量不是三大主條件之一，但可提高訊號品質。

### 7.1 整理後段量縮

```text
volume_MA10 < volume_MA50
```

更嚴格：

```text
volume_MA10 <= volume_MA50 * 0.75
```

### 7.2 回檔量縮

每次回檔期間的平均成交量應逐步下降：

```text
pullback_volume_2 < pullback_volume_1
pullback_volume_3 < pullback_volume_2
```

### 7.3 突破放量

突破日建議條件：

```text
breakout_volume >= volume_MA50 * 1.3
```

較嚴格：

```text
breakout_volume >= volume_MA50 * 1.5
```

## 8. 樞紐點與突破判斷

VCP 候選股不等於進場點。進場通常等待股價突破樞紐點。

### 8.1 樞紐點定義

樞紐點可定義為整理區壓力價：

```text
pivot_price = max(high in VCP lookback range)
```

也可使用最近幾個 swing high 的壓力區：

```text
pivot_price = max(recent_swing_highs)
```

### 8.2 接近突破條件

候選股可要求目前股價接近樞紐點：

```text
close >= pivot_price * 0.95
```

較嚴格：

```text
close >= pivot_price * 0.97
```

### 8.3 突破確認

```text
breakout =
  close > pivot_price
  and volume >= volume_MA50 * 1.3
```

保守版可要求：

```text
breakout =
  close > pivot_price
  and close > open
  and volume >= volume_MA50 * 1.5
```

## 9. 選股輸出

VCP 篩選結果建議輸出以下欄位：

| 欄位 | 說明 |
|---|---|
| symbol | 股票代號 |
| date | 篩選日期 |
| close | 當日收盤價 |
| stage2_pass | 是否符合第二階段上升趨勢 |
| contraction_count | 偵測到的收縮次數 |
| drawdowns | 各次回檔幅度 |
| durations | 各次回檔或整理天數 |
| last_drawdown | 最後一次回檔幅度 |
| volume_dry_up | 是否量縮 |
| pivot_price | 樞紐點價格 |
| distance_to_pivot | 距離樞紐點百分比 |
| breakout | 是否已突破 |
| score | VCP 綜合分數 |

## 10. VCP 評分建議

可用 100 分制排序候選股。

| 項目 | 分數 |
|---|---:|
| 第二階段上升趨勢 | 30 |
| 回檔幅度收縮 | 30 |
| 時間壓縮 | 20 |
| 成交量萎縮 | 10 |
| 接近樞紐點 | 10 |

### 10.1 分數解讀

| 分數 | 判斷 |
|---|---|
| 80 至 100 | 高品質 VCP 候選 |
| 60 至 79 | 可觀察候選 |
| 40 至 59 | 型態不完整 |
| 低於 40 | 不建議列入 |

## 11. 預設參數

| 參數 | 預設值 | 說明 |
|---|---:|---|
| lookback_days | 60 | VCP 觀察區間 |
| swing_window | 3 | 波段高低點偵測窗口 |
| min_contractions | 2 | 最少收縮次數 |
| contraction_ratio | 0.65 | 後一次回檔需小於前一次 65% |
| last_drawdown_max | 0.10 | 最後一次回檔上限 |
| duration_ratio | 0.75 | 後一次時間需小於前一次 75% |
| near_pivot_pct | 0.05 | 距離樞紐點 5% 內 |
| volume_dry_up_ratio | 0.75 | 10 日量低於 50 日量的 75% |
| breakout_volume_ratio | 1.30 | 突破量至少為 50 日均量 1.3 倍 |

## 12. 篩選流程

```text
for each stock:
  1. 計算 MA50、MA150、MA200、成交量均量、52 週高低點
  2. 判斷是否符合第二階段上升趨勢
  3. 若不符合，排除
  4. 在最近 40 至 80 日內偵測 swing high / swing low
  5. 組合 swing high -> swing low 作為 contraction
  6. 計算每次回檔幅度
  7. 判斷回檔幅度是否逐次收縮
  8. 計算每次 contraction 的時間長度
  9. 判斷時間是否壓縮
  10. 判斷成交量是否萎縮
  11. 計算 pivot_price 與 distance_to_pivot
  12. 計算 VCP score
  13. 輸出符合門檻的候選股
```

## 13. 通過條件

### 13.1 候選股通過條件

```text
stage2_pass = true
and contraction_count >= 2
and drawdown_contracting = true
and time_compression = true
and last_drawdown <= 0.10
and close >= pivot_price * 0.95
```

### 13.2 高品質候選股條件

```text
stage2_pass = true
and contraction_count >= 3
and drawdown_contracting = true
and time_compression = true
and volume_dry_up = true
and last_drawdown <= 0.08
and close >= pivot_price * 0.97
and score >= 80
```

### 13.3 突破股條件

```text
candidate_pass = true
and close > pivot_price
and volume >= volume_MA50 * 1.3
```

## 14. 排除條件

符合以下任一條件時，應排除：

- close < MA200。
- MA200 仍明顯向下。
- 近 120 日漲幅不足，缺乏強勢股特徵。
- 整理區跌破前一個重要波段低點。
- 最後一次回檔幅度仍大於 15%。
- 整理期間成交量持續放大且價格無法上漲。
- 距離樞紐點過遠，例如超過 10%。
- 股價已經突破過久且離樞紐點過遠，追價風險過高。

## 15. 實作注意事項

- VCP 偵測容易受單日長上影線或長下影線影響，必要時可用收盤價取代最高價與最低價。
- swing_window 太小會產生過多雜訊，太大會漏掉短期收縮。
- contraction_ratio 不宜設得過嚴，否則容易漏掉實務上不完全標準但仍有效的型態。
- VCP 候選股應搭配大盤環境使用。若大盤處於明顯空頭，突破成功率通常下降。
- 選股結果應回測不同參數，例如 lookback_days、swing_window、contraction_ratio、last_drawdown_max。

## 16. 範例

### 16.1 符合 VCP

```text
近 120 日漲幅：45%
close > MA50 > MA150 > MA200
MA200 最近 30 日上升

第 1 次回檔：100 -> 80，回檔 20%，時間 20 天
第 2 次回檔：98 -> 88，回檔 10%，時間 10 天
第 3 次回檔：96 -> 91，回檔 5%，時間 5 天

volume_MA10 < volume_MA50 * 0.75
close 距離 pivot_price 小於 3%
```

判斷：

```text
符合高品質 VCP 候選股
```

### 16.2 不符合 VCP

```text
close < MA200
MA150 < MA200
近 120 日漲幅不足
第 1 次回檔 8%
第 2 次回檔 15%
第 3 次回檔 12%
```

判斷：

```text
不符合第二階段上升趨勢，且回檔幅度未收縮
```

## 17. 結論

VCP 選股應先看趨勢，再看收縮，最後看突破。

核心公式：

```text
VCP 候選股 =
  第二階段上升趨勢
  + 回檔幅度逐次收縮
  + 整理時間逐次壓縮
  + 成交量萎縮
  + 接近樞紐點
```

進場確認：

```text
放量突破樞紐點
```

風控建議：

```text
跌破最後一次收縮低點，或跌破買點 5% 至 8%，應考慮停損
```
