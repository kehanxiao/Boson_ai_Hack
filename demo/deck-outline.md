# Demo deck: "ERwait" (make this as `demo/deck.pdf`)

This is a fictional MScAC-style internship project. `demo/deck.pdf` is generated from this outline by `server/scripts/make_placeholder_deck.py`.
The **planted weaknesses** are deliberate: they give the examiner something to catch in the demo video. Don't fix them.

| # | Title | Content | Planted weakness (examiner target) |
|---|---|---|---|
| 1 | ERwait: Forecasting ER Wait Times | Subtitle: MScAC internship project, Toronto hospital network (fictional). Presenter name. | none |
| 2 | The Problem | Long ER waits; ~1 in 20 patients leave without being seen; goal: forecast the next 4 hours of wait time per hospital. | none (sets context) |
| 3 | Headline Result | Big text: **"Our model is 40% better."** One bar chart with no axis labels. | **No baseline, no metric.** "40% better than *what*?" |
| 4 | Data | 2 years of triage records, 1.2M visits. Features include **"time to first physician"**. "We removed outliers." | **Target leakage** (time to physician is part of the wait), and the outlier removal is unexplained |
| 5 | Method | Gradient-boosted trees with **"LightGBM (released by Google in 2020)"**. Rolling-window validation. | **Factual error for the web fact-check.** LightGBM is Microsoft's, open-sourced around 2016–2017 |
| 6 | Feature Engineering | 14 dense bullets in small font (lags, holidays, weather, triage mix, staffing…). | **Text-crammed slide**, unreadable; invites "what are the top 3?" |
| 7 | Deployment | "Ready for deployment across all Ontario hospitals." | **Overclaim.** Validated on one hospital network only |
| 8 | Conclusion & Future Work | Recap, plus "add real-time bed data". | none |

## Presenter script notes for the demo
- **Time limit 5:00, Q&A 2:00.** Deliberately spend too long on slides 4 and 6 so the T−2:00 reminder fires on slide 6.
- **Ignore the first reminder** (keep talking): this triggers escalation and holding the floor. Acknowledge the second ("Okay, noted").
- On slide 3, say the "40% better" line confidently and keep going; this is the cold-open interjection.
- On slide 5, read the LightGBM line aloud; this triggers the fact-check.
- **Q&A:** answer the leakage question partly in Indonesian, and use one Mandarin phrase in another answer (see `sample-log.jsonl`).
