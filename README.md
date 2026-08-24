# score-the-code

## Dataset → Prompt mapping

Code refers to sets by number (`DataSet2`, `DataSet5`, `DataSet9`, `EssaySet1`). Here is what each number means:

| Code name | Dataset | Essay set | Paper category | Topic |
|---|---|---|---|---|
| `DataSet2` | ASAP-SAS (`train.tsv`, `EssaySet` col) | 2 | Science subset (3 components) | Science — **Polymer Investigation** (stretchability of plastics) |
| `DataSet5` | ASAP-SAS | 5 | Biology subset (1 component) | Science — **Protein Synthesis** (list 4 major steps) |
| `DataSet9` | ASAP-SAS | 9 | English subset (4 components) | Science — **Orbiting Junk** (space junk article, persuasive response) |
| `EssaySet1` | ASAP-AES (`training_set_rel3.tsv`, `essay_set` col) | 1 | Essay Set (5 components) | **Computers** — letter to newspaper on effects of computers |

- ASAP-SAS = short-answer responses (multi-agent scripts `asap_sas_*.py`, prompt dir `prompts/ASAP-SAS/DataSet{2,5,9}`).
- ASAP-AES = essay responses (`asap_aes_*.py`, prompt dir `prompts/ASAP-AES/EssaySet1`).

Prompt text lives in `prompts/<dataset>/<SetN>/question.txt`.

### Paper subsets vs. repo data — NOT a 1:1 match

The paper (AutoSCORE.pdf, Table 1) groups ASAP data into four categories: **Science subset** (3 rubric components), **Biology subset** (1 component), **English subset** (4 components), **Essay Set** (5 components). Each paper subset aggregates multiple essay sets and is much larger (20% validation samples: Science n=258, Biology n=370).

The datasets in this repo are **small custom samples (100 rows each)** covering only one essay set per paper category:

- Paper Science subset (multiple sets) → only `DataSet2` present here
- Paper Biology subset (multiple sets) → only `DataSet5` present here
- Paper English subset (multiple sets) → only `DataSet9` present here
- Paper Essay Set (multiple sets) → only `EssaySet1` present here

So the four paper categories are represented, but the repo does **not** contain the full paper datasets. Sizes do not match the paper's reported n values.

## Results


| Model | Set 2 (Science) QWK | Set 5 (Biology) QWK | Set 9 (English) QWK | Set 1 (Essay) QWK |
|---|---|---|---|---|
| Llama-3.3-70B-Instruct-Turbo (AutoScore) | 0.660 | 0.673 | 0.428 | 0.090 |
| Qwen2.5-7B-Instruct-Turbo (AutoScore) | 0.405 | 0.691 | 0.390 | 0.049 |

## Metrics explained

Each metrics JSON reports these values (all rounded to 3 decimals):

| Metric | Meaning | Range | Higher/lower better |
|---|---|---|---|
| **QWK** (Quadratic Weighted Kappa) | Agreement between predicted and human scores, weighted by distance (bigger score gaps penalized more). Standard metric in AES/ASAP | −1 … 1 | Higher |
| **Accuracy** | Exact-match rate of predicted vs. human score | 0 … 1 | Higher |
| **AdjAccuracy** | Within ±1 score point of human score | 0 … 1 | Higher |
| **MAE** (Mean Absolute Error) | Avg absolute difference, predicted vs. human | 0 … ∞ | Lower |
| **MSE** (Mean Squared Error) | Avg squared difference (penalizes large errors) | 0 … ∞ | Lower |
| **RMSE** (Root Mean Squared Error) | Square root of MSE, same units as score | 0 … ∞ | Lower |
| **CohenKappa** | Inter-rater agreement with chance correction | −1 … 1 | Higher |
| **Pearson** | Linear correlation, predicted vs. human | −1 … 1 | Higher |
| **Spearman** | Rank correlation (monotonic agreement) | −1 … 1 | Higher |
| **KendallTau** | Rank correlation based on concordant pairs | −1 … 1 | Higher |

Interpretation notes:

- QWK/CohenKappa: 0 = chance-level agreement, 1 = perfect, <0 = worse than chance. QWK usual benchmarks: <0.2 slight, 0.2–0.4 fair, 0.4–0.6 moderate, 0.6–0.8 substantial, >0.8 near-perfect (Landis & Koch scale).
- Pearson/Spearman/Kendall: correlation strength, not agreement — high correlation can still mean offset scores.
- MSE/RMSE/MAE: lower is better; MAE easiest to read (same units as the score scale). Essay Set 1 uses a 6-point scale, so its MAE/RMSE look larger than SAS (3-point scale) — not directly comparable across sets.
- Set 1 (Essay) shows QWK 0.090 but Pearson 0.684 — strong correlation, near-zero agreement. Classic sign of systematic score offset (e.g. predicted scores shifted vs. human). Check the CSV to diagnose.