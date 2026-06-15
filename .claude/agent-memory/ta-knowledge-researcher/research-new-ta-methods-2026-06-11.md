---
name: research-new-ta-methods-2026-06-11
description: 2026-06-11 對台股 AI 選股平台研究 6 個新技術分析手法的可落地性評估（Pocket Pivot / Mansfield RS / Supertrend出場 / Weinstein Stage2 / 投信籌碼+技術 / RSI 隱性背離）
metadata:
  type: project
---

## 研究摘要（2026-06-11）

本次為台股智能選股平台尋找可落地成新「分析師策略」的技術分析手法，研究了 6 個候選方法。

### Top 2~3 建議
1. **Supertrend ATR 追蹤出場模組**（最優先）：不增加新進場，升級現役 bb-trend 的出場邏輯；自適應波動、規則化難度最低、台灣電子股實證存在（TEJ 2019-2024 CAGR 25.88% Sharpe 1.84）。與系統已有的 20MA 出場比較，ATR(10)×3.0 更科學。
2. **投信連續買超籌碼進場過濾器**（高優先）：FinLab 台股實證投信 10 日累計買超≥15,000 張 → 年化 17.5%；加技術條件可到 CAGR 31.68%、Sharpe 0.99。平台已有 chip_institutional 表，可接入。需注意：逆向外資策略（外資連賣）反而年化 -11.2%，要避免。
3. **Pocket Pivot（口袋支點）**（中優先）：在 10MA/20MA 附近量能突破（當日量＞過去 10 日最大下跌量）；與 VCP/spring 互補；Morales&Kacher 原著有實例驗證，量化回測樣本仍不足。

### 其他候選方法評估
- **Mansfield RS**：個股價格 vs 大盤的相對強度比較（個股/指數SMA200-1×100），值>0且上升為強勢股。適合作為任何分析師的「市場相對強度過濾器」而非獨立策略。無足夠正式回測數據。
- **Weinstein Stage 2 突破**：周線30MA多頭 + 量能放大突破箱型，邏輯清晰但需要「周線」判斷，與日線平台整合有週期轉換的工作量；與 strat-5-10-20 高度相似（均線多頭+突破），差異化低。
- **RSI 隱性背離（Hidden Bullish Divergence）**：上升趨勢回調中 price higher-low 但 RSI lower-low，信號趨勢續抱。反指標傾向（過早入場），量化定義模糊，獨立策略可行性低，更適合作為既有策略的確認過濾。

### 方法已確認「系統尚未有」
- Supertrend（系統有 bb-trend 20MA 出場，但非 ATR 動態出場）
- 投信籌碼進場過濾（系統有 chip_institutional 資料但現無任何策略使用它）
- Pocket Pivot（系統有 VCP 突破，但 Pocket Pivot 針對均線附近盤整再發動，和 VCP 不同場景）
- Mansfield RS 分數（系統無 RS 評分，只有大盤寬度過濾）

### 知識邊界確認
已有：VCP波動收縮突破(strat-vcp) / 均線多頭排列順勢(strat-5-10-20) / 趨勢續抱出場(strat-bb-trend) / Wyckoff spring量縮假跌破(strat-spring) / ML邏輯回歸(ml-logreg)
尚無：ATR動態追蹤出場 / 籌碼面進場過濾 / 相對強度評分 / Pocket Pivot類型進場

**Why:** 用戶要求探索新技術分析手法，為平台引進差異化分析師策略。
**How to apply:** 未來提案新策略時，先參照此研究排除已研究過的方法，優先考慮 Supertrend 出場模組化 和 投信籌碼過濾器 兩個最具落地價值的方向。

相關記憶：[[empirical-selection-principles]] [[strat-bb-trend-results]] [[strat-vcp-results]]
