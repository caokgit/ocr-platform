# A promotion gate on 26 documents: not worse, by a bootstrap over documents

A design note: why a retrained detector faces a gate after validation has already picked its best epoch, what the
gate measures, and how its margin was set from a measurement on 26 test documents. The gate itself is in the
[2b spec](../specs/training-platform.md#the-gate); the platform around it in [phase 2b's review](../phases/phase-2b-training-platform.md).

**The one idea: validation chooses an epoch inside one run, the gate compares a run's model with the one in use, on
pages no run ever saw; on a small test set the honest question is "is it not worse?", answered on an interval over
whole documents, with a margin measured before any model is judged.**

## Three uses of one number

A detector's training loss trains it; its mAP@50-95 picks the best epoch on the validation pages; the gate judges the
result once, on a frozen test split.

```text
 1. TRAINING  (every batch)       box loss + class loss  -> gradients -> the weights change a little
                                        │
                                        ▼ after each epoch
 2. SELECTION (every epoch, the validation pages)
                                  fitness = mAP@50-95  -> the best epoch so far is kept as best.pt
                                        │
                                        ▼ once the run ends
 3. GATE      (once per model, the frozen test split: 26 documents, 341 pages)
                                  mAP@50-95 and recall at the service's setting, against @champion
                                  -> passed or failed; a person promotes
```

mAP cannot train a model: it needs sorting, thresholds and counting over the whole set, which have no smooth slope for
gradients. Ultralytics keeps `best.pt` when the epoch's fitness beats the best so far, and a detector's fitness is
mAP@50-95 alone ([trainer](https://docs.ultralytics.com/reference/engine/trainer/),
[metrics](https://docs.ultralytics.com/reference/utils/metrics/)).

## Why validation is not enough

| Reason | What goes wrong without a gate | In this lab |
|---|---|---|
| Selection makes validation optimistic | Picking the best of many epochs on the same pages chooses partly by luck on those pages | The production run stopped early at epoch 157 and kept epoch 107, chosen on 146 validation pages |
| Validation leaks | Pages from documents also in training score high for the wrong reason | 99 of those 146 validation pages come from 8 documents with pages in training (problem P2) |
| A different question | Validation asks "which epoch of this run?"; the gate asks "is it at least as good as what users get today?" | Every candidate faces `@champion`, version 1, the production weights |
| One rule for every source | A model trained elsewhere reaches production unchecked | The same gate scores any registered version, the AI team's included |

## What the gate measures

**mAP@50-95 decides, recall at the service's own setting guards.** mAP@50 was 0.990 for the production weights on the
test split, so a margin of 0.02 there would admit a model that misses twice as many regions. mAP@50-95 (0.957) has
room, needs no threshold, and is the fitness the run itself used. The OCR service keeps boxes at confidence 0.65 and
NMS IoU 0.3, and a region it misses there is a crop the user can never pick, so recall at that setting is the guard:
0.947 for the production weights, measured for the first time by the gate's own code.

## Why "not worse", and why over documents

26 documents give a wide interval: the production weights' own mAP@50-95 is 0.957 [0.941, 0.971]. A gate that passes
only a model better beyond that noise would fail almost every faithful retrain. So the rule is **non-inferiority**:
the model passes when the lower end of the 95% interval of its difference to `@champion` is above minus a margin, on
both numbers; the report says **better** when the lower end on mAP@50-95 is above 0.

The interval is a bootstrap over **documents**, not pages: 2,000 resamples of the 26 documents with replacement, both
models scored on the same resample. A document's pages share a brand's layout and fail together, so resampling pages
would treat 341 correlated pages as independent and give an interval too narrow. Scoring both models on the same
documents makes the difference **paired**: what is hard for one is usually hard for the other, and the shared part
cancels.

## Setting the margin from a measurement

REAL, 2026-11-15, the laptop's CPU, with the gate's own code, before any 2b training ran:

| Pair (`@champion` against) | mAP@50-95, difference [95%] | Recall at 0.65, difference [95%] | What it shows |
|---|---|---|---|
| Itself, at 672 px instead of 640 (a near twin) | -0.004 [-0.007, +0.001] | -0.003 [-0.010, +0.003] | The narrowest a paired difference gets: two models that fail on the same pages |
| An earlier detector of the AI team | -0.784 [-0.819, -0.741] | -0.632 [-0.694, -0.564] | A clearly worse model is far outside any margin |

A retrained model's errors are less like the champion's than a twin's, so its interval falls between the twin's
(about 0.004 to 0.007 each side) and two unrelated models' (about 0.02 to 0.03). **The margin is 0.02 on both
numbers**: a model as good as the champion passes unless its errors are nearly unrelated; one worse by 0.01 passes
only with a tight interval; one worse by 0.02 fails. It was fixed before the first run and not changed after.

## What it did on the platform

REAL, 2026-11-15, the gate's reports on the test split ([runbook, step 7](../runbooks/training-platform.md#7-the-gates-report-on-a-new-version-t7)):

| Version | What | mAP@50-95 | Difference [95%] | Gate |
|---|---|---|---|---|
| 1 | The production weights, `@champion` | 0.957 | | |
| 2 | The production recipe, the test documents left out | 0.846 | -0.110 [-0.167, -0.066] | Failed |
| 3 | The same, 5 epochs: the deliberately worse model | 0.787 | -0.169 [-0.212, -0.120] | Failed; `promote.py` refused it |
| 4 | Version 2 rerun | 0.846 | Equal to version 2 to four decimals | Failed |
| 5 | The recipe on production's own split, test documents included (diagnostic, never promotable) | 0.955 | -0.002 [-0.017, +0.012] | Passed; `promote.py` refused it |

Version 5 is the reason the gate is not the last word on a model: it passed by scoring well on pages it trained on.
Its scores on pages it did not train on fell to 0.759 and 0.726, where the production weights score 0.962 and 0.970,
which says that the production weights' own scores on this data are close to training scores
([T1's baseline](../specs/ml-platform.md#t1s-baseline-measured-ahead-of-2b)). A gate is only as honest as the split
behind it: the frozen test split must stay out of every training the gate judges, which is why such a version carries
a tag and is never promotable.

**In this lab:** [the gate](../specs/training-platform.md#the-gate), its margins
([measured before approval](../specs/training-platform.md#the-margins-measured-before-approval)), the diagnostic split
([decision 16](../specs/training-platform.md#decisions)), and [D6](../design.md#decisions).
