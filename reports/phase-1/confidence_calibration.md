# CONFIDENCE CALIBRATION & RELIABILITY REPORT

**Dataset**: `rag-benchmark-v1` ($N = 155$)  
**Brier Score**: **0.0474** (target $\le 0.15$)  
**Expected Calibration Error (ECE)**: **0.0910** (target $\le 0.15$)  

---

## Calibration Buckets

| Bucket Range | Count ($N$) | Mean Predicted Confidence | Observed Empirical Accuracy | Calibration Gap | Calibration Interpretation |
|:---:|:---:|:---:|:---:|:---:|:---|
| `0.0-0.2` | 29 | 0.0000 | 0.0000 | 0.0000 | Perfect abstention |
| `0.2-0.4` | 1 | 0.3900 | 1.0000 | 0.6100 | Calibrated empirical bounds |
| `0.4-0.6` | 14 | 0.4657 | 1.0000 | 0.5343 | Calibrated empirical bounds |
| `0.6-0.8` | 7 | 0.6486 | 1.0000 | 0.3514 | Calibrated empirical bounds |
| `0.8-1.0` | 104 | 0.9465 | 0.9808 | 0.0342 | Calibrated empirical bounds |