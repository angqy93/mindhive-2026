# Evaluation

## 1. The harness

One command, run from the repo root:

```bash
uv run python submission/evaluate.py
```

It runs the matcher on the 420 labelled training lines, compares every answer with the label, and prints the results. It does this twice: once against the original labels (`data/order_lines_train.csv`) and once against the corrected labels (`submission/data/order_lines_train_corrected.csv`). Why there are two label sets is explained in section 4.

### Scoring fairly: 5-fold cross-validation

The matcher learns two things from labelled lines: the confidence calibration, and the similarity at which embeddings may answer on their own. If it were scored on the same lines it learned from, it would be marking its own exam, and the confidence numbers would look better than they really are.

So the 420 lines are split into 5 parts. The matcher learns from 4 parts and is scored on the 5th, and this is repeated until every part has been scored once. Every line is scored by a matcher that never saw it. The split uses a fixed seed, so every run gives the same numbers.

This does not cover the rules that were chosen by hand while looking at all 420 lines: the fuzzy success line of 70, the review floor of 60 (temporary, see section 2), the 1-point gap check, the word check and the +1/+2 in the calibration. The training numbers are therefore still somewhat optimistic. The real test is the holdout, which only Mindhive can score.

### How the confidence is calibrated

The `confidence` in `predictions.csv` answers one question: of the labelled lines that ended with the same reason code and a similar score, how often was the top candidate the right item? It is a measured hit rate, so 0.9 means the same thing whether it came from a barcode, fuzzy matching or embeddings.

1. **Collect the evidence.** Every labelled line is run through the matcher. For each line the calibration keeps its reason code, the stage's own score (100 for exact matches, the fuzzy ratio, or the embedding similarity) and whether the top candidate was the labelled item. A blank label is never matched.
2. **Keep each reason code apart.** A fuzzy ratio of 70 and an embedding similarity of 70 do not mean the same thing, so each reason code gets its own calibration.
3. **Group the scores.** Within one reason code, the lines are sorted by score and grouped with isotonic regression, so that a higher score never has a lower hit rate.
4. **Never claim certainty from a few lines.** Each group reports (right + 1) / (lines + 2), as if it had seen one extra right and one extra wrong answer. This is not invented data: it is a standard estimate (Laplace's rule of succession) for "how likely is the next line to be right", rather than "what happened in the lines we saw". 13 right barcode answers out of 13 do not prove a barcode answer can never be wrong, so it reports 14/15 = 0.933 instead of 1.000.
5. **Keep the groups in order.** The +1/+2 pulls small groups towards 50% more than large ones, which can put a small low-score group above a larger high-score group. A second isotonic pass, weighted by group size, merges such pairs.

A reason code never seen in the labelled lines gets 0.5: no evidence either way. `run.py` fits the calibration on all 420 corrected lines; the harness fits it inside each fold (section 1).

Confidence per reason code, fitted on all 420 corrected lines:

| Reason code | Lines | Right | Confidence |
|---|---|---|---|
| name_exact | 166 | 166 | 0.994 |
| fuzzy_match | 67 | 67 | 0.986 |
| sku_map_hit | 63 | 63 | 0.985 |
| barcode_hit | 13 | 13 | 0.933 |
| ambiguous_near_tie | 5 | 3 | 0.500 to 0.667 |
| fuzzy_low_score | 6 | 1 | 0.300 |
| embedding_several_fit | 3 | 0 | 0.200 |
| ambiguous_twins | 10 | 1 | 0.167 |
| not_an_item | 4 | 0 | 0.167 |
| embedding_detail_mismatch | 11 | 0 | 0.077 |
| ambiguous_several_fit | 32 | 0 | 0.029 |
| embedding_near_tie | 40 | 0 | 0.024 |

The weakness of step 4 is visible here: small lanes are pulled towards 50%, so `not_an_item` reports 0.167 although "thanks bro" is certainly not an item. The pull shrinks as a lane gets more lines.

Alternatives that were measured during development (one-off 5-fold checks, not printed by the harness; Brier score, lower is better):

| Method | Brier | Why not chosen |
|---|---|---|
| Plain isotonic regression, no +1/+2 | 0.0165 | Claimed exactly 0% on 97 lines, and 5 of them were right |
| Isotonic with +1/+2 and the second pass (chosen) | 0.0140 | |
| Logistic regression on reason code, score and the gap between the top two | 0.0158 | The gap adds nothing here: all 67 fuzzy answers that passed the gap check were right whatever the gap, and near ties already have their own reason code |
| Softmax over the embedding similarities | not calibrated | Spread over hundreds of items, every line gets about 0.003. Sharpened with a temperature, a vague line ("full cream milk uht 1l", 0.144) scored above a right one ("sisu mozzarella", 0.130), and the temperature itself would have to be learned from labels |
| Raw scores as confidence | not calibrated | MiniLM gives "Cadbury Dairy Milk 165g" a similarity of 0.78 to a full cream milk the company sells; a similarity is not a probability |

### What the embeddings add

README section 5.2 asks for the gain of the embedding stage over the non-semantic baseline. The harness measures it by running with and without the stage:

```bash
uv run python submission/evaluate.py --no-embeddings
```

| | With embeddings | Without (regex and fuzzy only) |
|---|---|---|
| Precision, coverage, wrong autos, net value (both label sets) | identical | identical |
| Per tenant and per noise group, including recall@3 | identical | identical |
| p95 time per line | 20.2 ms | 0.5 ms |

The measured gain is 0. All 54 training lines that reach the embedding stage are labelled blank, so it has no right answer to add and no suggestion that can be scored. The stage is kept as designed (DESIGN.md section 3): it only adds suggestions for the reviewer, and it never answers on its own until labelled lines show its answers clear 92.7%. Its cost is about 20 ms per line that reaches it, well inside the 250 ms budget. If production data shows the same result, the stage should be removed.

### Is the fuzzy success line overfitted?

The most important hand-picked rule is the fuzzy success line of 70, because it decides what fuzzy matching answers automatically. Three checks were run on it, on the 70 fuzzy answers that pass both the gap check and the word check, whatever their score. The harness prints all three (`IS THE FUZZY SUCCESS LINE OVERFITTED?`).

**1. Does the exact number matter?** Moving the line from 60 to 80 barely changes anything:

| Fuzzy line | Answers | Right (corrected labels) | Right (original labels) | Lower bound (original labels) |
|---|---|---|---|---|
| 60 | 67 | 67 | 66 | 93.6% |
| 65 | 67 | 67 | 66 | 93.6% |
| 70 (ours) | 67 | 67 | 66 | 93.6% |
| 75 | 66 | 66 | 65 | 93.5% |
| 80 | 65 | 65 | 64 | 93.4% |

No answer that passes both checks scores between 60 and 72, so any line in that range gives the same result. The gap check and the word check do the work, not the exact number, so 70 is not tuned to a knife-edge.

**2. Re-choosing the line without seeing the scored lines (5-fold).** The line was chosen again with the 92.7% rule from 4 of the 5 folds, then tested on the 5th.
- Corrected labels: the rule picked 72, 76, 72, 72 and 72. On the unseen lines, 66 of 66 answers were right.
- Original labels: in 4 of the 5 folds the rule found no line at all, so fuzzy would never answer automatically. With one wrong answer and only about 53 answers per fold, the lower bound falls below 92.7%.

**3. Choosing on one tenant, testing on the other (corrected labels).**
- Chosen on acme only: line 76. On nordic, 27 of 27 answers were right.
- Chosen on nordic only: no line. Nordic has only about 27 fuzzy answers, and even with all of them right the rule needs at least 35 before the lower bound clears 92.7%.

What this shows: the line of 70 is not overfitted. It is stable from 60 to 80, it held on unseen folds, and it transferred from acme to nordic. The real weakness is how little evidence there is. Fuzzy auto-answering rests on about 67 answers, and one or two wrong labels are enough to stop the 92.7% rule from qualifying. For the same reason a new tenant cannot earn its own line from its own data at first, and uses the line learned on the other tenants (the cold start in DESIGN.md section 2).

### What it prints

| Metric | Meaning |
|---|---|
| precision on auto | Of the lines answered automatically, the share that were right |
| coverage | The share of all lines answered automatically |
| wrong autos | Lines answered automatically with the wrong item |
| net value | Seconds saved using section 1 of DESIGN.md: +20 per right auto, −40 per line sent to a human, −800 per wrong auto. Printed next to the all-human baseline (every line to a human). |
| accuracy | The share of lines where the answer equals the label, counting an abstention on a blank label as right. Printed only to show why it misleads (section 2). |
| refused | Of the lines with no right answer, the share that were not answered automatically |
| recall@3 | Of the lines sent to a human that did have a right answer, the share where it was among the 3 suggestions |
| cross-tenant violations | Any answer or suggestion from the other tenant's catalogue. Must be 0. |
| time per line | Median, p95 and max in milliseconds, after one warm-up line (README: cold caches excluded). Budget: p95 ≤ 250 ms. |

Each metric is printed for all lines, per tenant, and per noise group. The harness also prints the precision vs coverage curve (section 2).

### Noise groups

The data does not say what kind of mess a line has, so the groups are defined here. The matcher already has a fix for the mess: normalization. The groups check whether that fix worked, by showing for each kind of mess how often the matcher still gets it right.

Each line is checked against every rule below and goes into every group it fits, because a line often has more than one kind of mess. For example, `need Sisu Chicken Breast Diced 5kg` has filler and is otherwise clean. The rules are in `submission/segments.py`.

| Group | Rule | Example |
|---|---|---|
| clean | The text is exactly an item name | `Tolsen Wall Plug 12mm Red` |
| barcode | The barcode field is filled, or the text contains an 8 to 14 digit number | |
| buyer_sku | The buyer SKU field is filled | SKU `003119277` |
| typo | A word is one letter off a catalogue word (a swap of two letters counts as one). Words with digits are left out, because "22mm" vs "24mm" is a different size, not a typo. Words under 4 letters are left out, because "fed" vs "red" is a different word. | `Vermmont`, `Prawnn`, `Pottao` |
| malay | Contains a word from the Malay list in stage 0 | `paip`, `putih`, `skru` |
| abbreviation | Contains a word from the abbreviation list in stage 0 | `FC MILK`, `S/S`, `ZP` |
| formatting | Filler words, list numbering (`1)`), a leading dash or `item:`, spaced dashes, double spaces, slashes between words | `- tolsen safety helmet red standard`, `Kanto/Masking/pita/48mm/High/Temp` |
| quantities_included | Packing words, an `x12` at the end, or the note "price quoted per outer" | `Vermont PVC Pipe 50mm Class D x12 case` |
| incomplete_order | Every word is a real catalogue word, but the line leaves out part of the item's name | `Kanto Ball`, `Stallion PVC 25mm E` |
| not_an_order | Tagged by hand: chatter and notes, not a product | `pls confirm stock first`, `thanks bro`, `subtotal`, `same as last month order` |
| not_in_catalogue | Tagged by hand: a product the company does not sell | `Cadbury Dairy Milk 165g`, `Makita LS1040 mitre saw 240v` |

- If no rule explains why a line is not exactly an item name, some word in it is wrong, so it counts as a typo. On the training lines that is 8 lines: trade wording (`SS304` for "Stainless 304", `GRINDING DISC` for "Angle Grinder Disc"), words stuck together (`SiusSalmon`) and typos in short words (`Siu … Mik`).
- not_an_order and not_in_catalogue are tagged by hand, because telling them apart needs judgement. Both have words the catalogue does not know. "same as last month order" is tagged not_an_order: it is a request, but the item is in the customer's order history, not in the text.
- Every line with a blank label falls into one of three groups: not_an_order (22), not_in_catalogue (35) or incomplete_order (45). incomplete_order includes exact item names that have a "(Bulk)" twin, such as `Tolsen Hex Bolt M8x50 HDG`, because the line does not say which of the two it means.

Limits of the groups:
- The malay and abbreviation groups only find words that are already on the stage 0 lists, the same lists the matcher uses. A Malay word that is not on the list lands in typo or nowhere, so these groups cannot show how the matcher does on Malay words it has never seen.
- The rules are approximate. They were checked by eye on all 420 lines.

### Results (corrected labels, 5-fold)

Overall: precision on auto 100%, coverage 73.6%, 0 wrong autos, net value +1,740 s against −16,800 s for all-human, 0 cross-tenant violations. Time per line: median 0.3 ms, p95 16.4 ms.

Per tenant:

| Tenant | Lines | Auto | Coverage | Precision | Net value | Refused | Recall@3 |
|---|---|---|---|---|---|---|---|
| acme | 260 | 189 | 72.7% | 100% | +940 | 100% | 75.0% |
| nordic | 160 | 120 | 75.0% | 100% | +800 | 100% | 100% |

Per noise group (a line can be in several):

| Group | Lines | Auto | Coverage | Precision | Net value | Refused | Recall@3 |
|---|---|---|---|---|---|---|---|
| clean | 77 | 68 | 88.3% | 100% | +1,000 | 100% | – |
| barcode | 13 | 13 | 100% | 100% | +260 | – | – |
| buyer_sku | 64 | 63 | 98.4% | 100% | +1,220 | – | 100% |
| typo | 42 | 38 | 90.5% | 100% | +600 | – | 75.0% |
| malay | 15 | 15 | 100% | 100% | +300 | – | – |
| abbreviation | 7 | 7 | 100% | 100% | +140 | – | – |
| formatting | 143 | 135 | 94.4% | 100% | +2,380 | 100% | 50.0% |
| quantities_included | 36 | 35 | 97.2% | 100% | +660 | – | 100% |
| incomplete_order | 130 | 81 | 62.3% | 100% | −340 | 100% | 75.0% |
| not_an_order | 22 | 0 | 0% | – | −880 | 100% | – |
| not_in_catalogue | 35 | 0 | 0% | – | −1,400 | 100% | – |

What this shows:
- Normalization works where it was aimed: every Malay and abbreviation line is answered, and so are 97% of the lines with quantities.
- incomplete_order is the weak spot: the lowest coverage (62.3%) of any group that has answers, and the only one with a negative net value. Normalization cannot help here, because the missing words are not in the line.
- No line that is not an order, or not sold by the company, was ever answered.
- The one buyer_sku line not answered is `NRD-T-0103` (`SISU MOZZARELLA`): its SKU mapping is an `inferred_match` at confidence 0.55, which is not trusted (DESIGN.md failure mode 5), so it went to a human with the right item as the first suggestion.

## 2. Why not accuracy

Accuracy here means the share of lines where the matcher's answer equals the label, counting an abstention on a blank label as right. The harness prints it only to show why it misleads.

| | Original labels | Corrected labels |
|---|---|---|
| accuracy | 92.4% | 97.9% |
| precision on auto | 92.6% | 100% |
| coverage | 73.6% | 73.6% |
| wrong autos | 23 | 0 |
| net value | −17,120 s | +1,740 s |
| all lines to a human | −16,800 s | −16,800 s |

### Accuracy treats "I don't know" the same as a wrong answer

On the corrected labels the matcher never gives a wrong answer. Its 309 automatic answers are all right, and the 102 lines with no right answer are all refused. Accuracy is still not 100%, because of 9 lines (2.1%) that had an answer but were sent to a human, for example `Tolsen Cablle Tie 3700mm White`, where 3700mm is equally close to the 300mm and the 370mm cable tie. Accuracy counts those 9 as errors, exactly like shipping the wrong goods. In fact none of them was answered: all 9 went to review, and for 7 of them the right item was among the 3 suggestions. They are listed in section 3.

The cost model in DESIGN.md section 1 does not: sending a line to a human costs 40 seconds, a wrong automatic answer costs 800, twenty times more. We would rather abstain than give a wrong answer. A matcher that guessed on those 9 lines could raise its accuracy and still lose time, because one wrong guess cancels out the saving of about 12.7 right answers.

### A high accuracy can still lose time

On the original labels, accuracy is 92.4%, which sounds good. But the net value is −17,120 s, worse than sending every line to a human (−16,800 s). The 23 "wrong" automatic answers cost 23 × 800 = 18,400 s, more than all 286 right automatic answers save. Accuracy cannot show this, because it counts every miss the same: the expensive ones and the cheap abstentions.

These 23 are not real mistakes by the matcher. In 22 of them the line is exactly an item's name, for example `Kanto Nitrile Glove M Blue`, and the pipeline found that item, but the original label is blank (abstain). The pipeline found the right item, and the blank label turned that find into a "wrong" answer. The 23rd, `ACM-T-0114` (`Stallion Self Drilling Screw #10 x 1'' Stainless`), is also labelled blank. Its text leaves out "410", but Stallion sells only one stainless #10 x 1" self drilling screw (the other is zinc plated), so the item is still certain. Section 4 argues these labels are wrong.

The labels were corrected only where the item is certain: the 22 lines whose text is exactly one item's name, plus `ACM-T-0114` (section 4). With those corrections, the same matcher with the same answers has 0 wrong automatic answers and saves 18,540 s against sending everything to a human, about 5.1 hours on 420 lines. Trusting or correcting 23 labels moves the result from a loss to a large saving, while accuracy only moves from 92.4% to 97.9%.

### What we use instead

- **Precision on auto**, which must stay at or above 92.7%, the break-even from DESIGN.md section 1.
- **Coverage**, the share of lines answered automatically. Within the precision limit, more is better.
- **Net value**, the seconds saved under the cost model, compared with sending every line to a human.
- **Abstention quality**: refused (of lines with no right answer, the share not answered) and recall@3 (of lines sent to a human that had an answer, the share where it was among the 3 suggestions).

### The operating-point curve

The curve shows what would happen at every possible operating point, not only ours. The lines are sorted by confidence. For each threshold t, every line with confidence at least t is answered automatically with its top candidate, and the rest go to a human.

Corrected labels (5-fold):

| t | Coverage | Precision | Net value |
|---|---|---|---|
| 0.993 | 30.7% | 100% | −9,060 |
| 0.992 | 39.5% | 100% | −6,840 |
| 0.982 | 52.9% | 100% | −3,480 |
| 0.981 | 62.6% | 100% | −1,020 |
| 0.979 | 70.5% | 100% | +960 |
| **0.900** | **73.6%** | **100%** | **+1,740** (best, our operating point) |
| 0.167 | 78.8% | 94.6% | −11,700 |
| 0.040 | 84.0% | 89.0% | −27,600 |
| 0.033 | 89.5% | 83.8% | −44,260 |
| 0.029 | 96.4% | 77.8% | −66,300 |

Original labels (5-fold):

| t | Coverage | Precision | Net value |
|---|---|---|---|
| 0.982 | 7.6% | 96.9% | −15,700 |
| 0.957 | 19.8% | 98.8% | −12,640 |
| 0.929 | 31.4% | 99.2% | −9,700 |
| **0.900** | **34.0%** | **99.3%** | **−9,040** (best) |
| 0.862 | 49.3% | 93.7% | −15,040 |
| 0.847 | 73.6% | 92.6% | −17,120 (our operating point) |
| 0.167 | 78.8% | 87.6% | −30,560 |
| 0.029 | 96.4% | 72.1% | −85,160 |

What the curve shows:
- On the corrected labels, our operating point is the best point on the curve: 73.6% coverage at 100% precision.
- Past it, coverage rises only by answering lines the matcher is unsure about, and the net value collapses. Going from 73.6% to 78.8% coverage adds 22 answers, of which 18 are wrong. The overall precision still reads 94.6%, above 92.7%, but those extra answers turn +1,740 s into −11,700 s. The 92.7% break-even has to hold for each extra answer, not only on average.
- On the original labels, the best point is only 34% coverage. The 22 exact-name lines labelled blank teach the calibration that exact-name answers are less reliable than they are, so they fall below the best threshold. This is a label problem, not a matcher problem (section 4).

### The review floor (ROC)

The curve above decides where automatic answering stops. A second line decides what happens to the lines fuzzy matching cannot answer (score below 70): at or above the review floor they go to **review**, where a person sees them with suggestions; below it they go to the embedding stage and are then **rejected**. The floor is 60. DESIGN.md section 2 leaves this line open until it is measured, so this is the measurement. The harness prints it (`REVIEW FLOOR (ROC)`).

60 training lines score below 70 with fuzzy matching. Only 1 of them has a right answer (`NRD-T-0103` `SISU MOZZARELLA`, score 64.4); the other 59 are not orders, products the company does not sell, or too vague.

| Floor | Lines sent to review | Answered lines kept for review | No-answer lines sent to review |
|---|---|---|---|
| 0 | 60 | 1/1 | 59/59 |
| 30 | 60 | 1/1 | 59/59 |
| 40 | 45 | 1/1 | 44/59 |
| 50 | 9 | 1/1 | 8/59 |
| 55 | 7 | 1/1 | 6/59 |
| **60 (current)** | **6** | **1/1** | **5/59** |
| 62 | 5 | 1/1 | 4/59 |
| 65 | 3 | 0/1 | 3/59 |
| 68 | 1 | 0/1 | 1/59 |
| 70 | 0 | 0/1 | 0/59 |

Why 60 and not another value:
- **Not above 64.4.** A higher floor rejects the only line with a right answer, so the reviewer never sees it with its suggestions (its right item is the first one).
- **Not much lower.** Every training line below 60 has no right answer (0 of 54). Lowering the floor only sends more of them to review: 8 at a floor of 50, 44 at 40.
- **Not 62 or 64, although they look slightly better.** They send one or two fewer no-answer lines to review, but choosing between 60 and 64 would be tuning to a single line. 60 leaves a margin below 64.4, so a similar line that scores a little lower still reaches a person.
- **The choice does not change any score.** Review and reject both cost −40 in the cost model, so precision, coverage and net value are the same for any floor. The floor only decides which lines a person sees with suggestions, which is why DESIGN.md section 2 leaves it to the team.

With only one line that has a right answer, this table cannot set the floor precisely. 60 stays a temporary value, to be measured again when more labelled lines below 70 are collected (section 5).

## 3. Error analysis

20 failures on the original labels, scored by the harness. 15 were chosen by hand; the other 5 were drawn at random (fixed seed) from the remaining wrong automatic answers: `ACM-T-0028`, `0062`, `0130`, `0150` and `0212`.

Cost class: **−800** is a wrong automatic answer, **−40** is a line sent to a human although a right answer existed (a missed +20).

### A. Formatting that cleans to an exact name (6 lines)

| Line | Text | Matcher answered | Cost class |
|---|---|---|---|
| ACM-T-0009 | `Remax/Ball/Valve/2"/SS304` | Remax Ball Valve 2" SS304 | −800 (label blank) |
| ACM-T-0015 | `- Hitex Angle Grinder Disc 7" Flap` | Hitex Angle Grinder Disc 7" Flap | −800 (label blank) |
| ACM-T-0062 | `Vermont/Ball/Valve/2"/Brass` | Vermont Ball Valve 2" Brass | −800 (label blank) |
| ACM-T-0157 | `Tolsen - PVC - Pipe - 25mm - Class - C` | Tolsen PVC Pipe 25mm Class C | −800 (label blank) |
| ACM-T-0177 | `- Vermont Self Drilling Screw #10 x 1-1/2" Stainless 410` | the same item | −800 (label blank) |
| ACM-T-0232 | `Remax  PVC  Pipe  32mm  Class  D` | Remax PVC Pipe 32mm Class D | −800 (label blank) |

**Root cause:** the label is blank, although once the formatting (slashes, dashes, double spaces) is cleaned, the text is exactly one item's name.
**Fix:** none in the matcher. Normalization already cleans the formatting, so the exact name is found and the answer is right. Each of these lines saves 20 seconds instead of costing 40, and this cleaning is what lets many orders be automated and raises coverage. The label is what is wrong (section 4).

### B. Exact catalogue names (4 lines)

| Line | Text | Matcher answered | Cost class |
|---|---|---|---|
| ACM-T-0028 | `Stallion Ball Valve 1-1/4" PVC` | the same item | −800 (label blank) |
| ACM-T-0130 | `Remax Self Drilling Screw #8 x 1" Zinc Plated` | the same item | −800 (label blank) |
| ACM-T-0150 | `Vermont Self Drilling Screw #10 x 1" Zinc Plated` | the same item | −800 (label blank) |
| ACM-T-0212 | `Stallion Self Drilling Screw #8 x 3/4" Stainless 410` | the same item | −800 (label blank) |

**Root cause:** the label is blank although the text is exactly the catalogue name. Abstaining on these would waste 40 seconds each.
**Fix:** none. The matcher answers them, which is right.

### C. Incomplete but still unique (1 line)

| Line | Text | Matcher answered | Cost class |
|---|---|---|---|
| ACM-T-0114 | `Stallion Self Drilling Screw #10 x 1'' Stainless` | Stallion Self Drilling Screw #10 x 1" Stainless 410 | −800 (label blank) |

**Root cause:** the line leaves out "410", and the label is blank. But the missing part does not remove the uniqueness: Stallion sells only one stainless #10 x 1" self drilling screw (the other is zinc plated). Fuzzy matching identified the item.
**Fix:** none. The matcher captured it correctly.

### D. Missed chances: too risky to answer automatically (8 lines)

| Line | Text | Right item | Items it could be | Cost class |
|---|---|---|---|---|
| ACM-T-0151 | `Tolsen Cablle Tie 3700mm White` | 370mm | 2 (300mm, 370mm) | −40 |
| ACM-T-0111 | `need Hitex PPVC Pipe 05mm Class E` | 50mm | up to 6 Hitex Class E sizes (15 to 50mm) | −40 |
| ACM-T-0233 | `1) Hitex Hx Bolt M6x0 Stainless 316` | M6x30 | 2 (M6x30, M6x50) | −40 |
| ACM-T-0179 | `Remax Ball Valve " 1PVC` | 1" PVC | 5 sizes (1/2" to 2") | −40 |
| ACM-T-0061 | `Vermont PVC Pipe 50mm Class D x12 case` | plain, not Bulk | 2 (plain, Bulk) | −40 |
| ACM-T-0250 | `pls send Kanto Nitrile Glove L` | L Blue | 2 (Blue, Black) | −40 |
| ACM-T-0209 | `pls send Masking Tape 24mm High Temp` | Tolsen (Bulk) | 8 (7 brands, plus Tolsen Bulk) | −40 |
| NRD-T-0103 | `SISU MOZZARELLA` | Shredded 1kg | 6 (Diced, Block, Shredded × 1kg, 2kg) | −40 |

**Root cause:** the line does not contain enough to pick one item. A size has a typo or a missing digit, or the colour, brand, pack or cut is left out. NRD-T-0103 also has a buyer SKU, but its mapping is an `inferred_match` at 0.55 confidence, which is not trusted.
**Fix:** none in the matcher. Guessing between n items is right about 1 time in n: 50% for 2 options, 12.5% for 8. That is far below the 92.7% break-even, and each wrong guess costs 800 seconds against 40 for asking a human. The checks did their job: every one of these lines went to review, and for 6 of the 8 the right item was among the 3 suggestions. ACM-T-0250 and ACM-T-0209 are also argued as label problems in section 4. Bulk was considered: the Bulk twin is sold by the carton of 144, so a rule "below 144 means plain" was tested, but 9 of the 10 twin lines in training are labelled blank, so it would have turned 9 safe abstentions into wrong answers (−7,200 s).

### E. A space in the wrong place (1 line)

| Line | Text | Right item | Matcher did | Cost class |
|---|---|---|---|---|
| ACM-T-0030 | `Hitex PVCP ipe1 5mm Class E` | Hitex PVC Pipe 15mm Class E | review (near tie) | −40 |

**Root cause:** the spaces are in different places ("PVCP ipe1 5mm" for "PVC Pipe 15mm"). This was not accounted for when the pipeline was built. It also shows the design working: when the matcher is not sure, it does not answer automatically, it abstains.
**Fix, still being considered:** compare the line with item names after removing all spaces. On the training lines this would match exactly one item for 3 lines (this one, `ACM-T-0220` and `NRD-T-0057`), all 3 right, and it touches no line with a blank label.

Pros:
- It is a general rule for misplaced spaces, not a patch for one line.
- On the training lines it was 3 out of 3 right, and it touched no line that should be abstained.
- It is deterministic and cheap, so it fits stage 1 next to the exact-name lookup.

Cons:
- The gain on the training lines is small. Only ACM-T-0030 changes from review to auto, which is +60 seconds; the other two are already answered by fuzzy matching.
- Joining words can change their meaning. "1 5mm" becomes "15mm", but a buyer could mean 1 piece of a 5mm item. A wrong join is a wrong automatic answer at −800.
- 3 lines is too little evidence to measure its precision with the 92.7% rule.
- It would change the other measurements, not just this line. Lines would move from fuzzy to exact-name answers, which changes how the confidence is calibrated and every number in sections 1 and 2. The harness would have to be rerun, and the regression baseline (section 5) reset.

Because the gain is small and the risk is a −800 answer, it is not added yet. It is the first candidate once production data shows how often spaces are misplaced.

### Grouped

| Kind | Groups | Lines |
|---|---|---|
| One bug | E: spaces in the wrong place | 1 |
| The same missing capability | D: the line lacks a detail (size, colour, brand, pack). The matcher cannot invent it; in production it would need the customer's order history or a question back to the customer. | 8 |
| Data problems that cannot be fixed in code | A, B and C: blank labels on lines whose item is certain | 11 |

## 4. The label problem

The labels in `data/order_lines_train.csv` are not all right. Three cases, argued below. The first two were corrected in `submission/data/order_lines_train_corrected.csv`; the original file is untouched, and the harness reports both (section 2).

### 1. Blank labels on lines that are exactly one item's name (22 lines)

Example: `ACM-T-0022` `Kanto Nitrile Glove M Blue`. Label: blank (abstain).

**Argument:** the text is exactly the name of one catalogue item, ACM-NITR0925, and no other item has that name. Nothing is missing and nothing is ambiguous, so there is no reason to abstain. 22 training lines are like this, all for acme. Some are already clean (`Stallion Ball Valve 1-1/4" PVC`); others become the exact name once the formatting is cleaned (`Remax/Ball/Valve/2"/SS304`, `Tolsen - PVC - Pipe - 25mm - Class - C`).
**Effect:** every one of them counts as a wrong automatic answer (−800) although the matcher picked the item the text names. They are why the original labels show 92.6% precision and a loss against sending everything to a human (section 2).
**Corrected to:** the item whose name the line is.

### 2. A blank label on a line that still names exactly one item (`ACM-T-0114`)

Text: `Stallion Self Drilling Screw #10 x 1'' Stainless`. Label: blank.

**Argument:** the line leaves out "410", but Stallion sells only two self drilling screws #10 x 1": Stainless 410 and Zinc Plated. "Stainless" rules out the zinc plated one, so the item is still certain.
**Corrected to:** ACM-SELF0720, Stallion Self Drilling Screw #10 x 1" Stainless 410.

### 3. A label that names one item when the line could be several (`ACM-T-0209`)

Text: `pls send Masking Tape 24mm High Temp`. Label: ACM-MASK0286B, Tolsen Masking Tape 24mm High Temp (Bulk).

**Argument:** the line names no brand and does not say Bulk. 8 items fit it: seven brands of 24mm high temperature masking tape, plus the Tolsen Bulk version. Nothing in the text points to Tolsen, and nothing points to Bulk. The task is under-specified: the right answer is to ask, not to pick one. `ACM-T-0250` is the same kind of case: `pls send Kanto Nitrile Glove L` is labelled Blue, but Kanto sells the L glove in Blue and Black, and the line gives no colour.
**Not corrected:** the matcher already sends both lines to a human, so the label does not change any automatic answer. It only makes them count as missed chances.

### In production

- **Correct only what is certain, and keep the original.** A label is only corrected when the item is certain, as in cases 1 and 2. The original labels are kept next to the corrections, so the corrections can be used to improve the pipeline, and its results can always be compared on both.
- **Do not label under-specified lines; ask for clarification.** A line like case 3, where several items fit and the text does not say which, is not given an item as its label. The customer is asked which one they meant.

## 5. Regression safety

A regression is a change that makes something that used to work worse. Every change to the matcher is scored by the harness before it ships, and compared with the last accepted run.

### What never changes

The precision floor of 92.7%. It comes from the cost model in DESIGN.md section 1 (break-even between a right answer, a wrong answer and asking a human), not from the data, so no change to the data or the matcher moves it.

### Gates

A change is blocked if any of these fails:

| Gate | Blocks the change if |
|---|---|
| Cross-tenant violations | there is any (more than 0) |
| Precision on auto | it is below 92.7% |
| Wrong automatic answers | there are more than in the last accepted run (now 0 on the corrected labels) |
| pytest tests | any test fails (they also check that the same input gives the same output, and the output format) |

Wrong automatic answers have their own gate because precision can stay above 92.7% while new wrong answers appear, each costing 800 seconds.

How a failed gate breaks the build: `uv run python submission/evaluate.py` checks the first three gates at the end of its run, prints `GATES: PASS` or `GATES: FAIL` with the reason, and exits with code 1 on a failure. `uv run pytest` exits with code 1 when a test fails. A CI pipeline runs both on every change and refuses the change when either exits with 1. The last accepted number of wrong automatic answers is kept in `submission/eval_baseline.json`, and it is only updated when a run is accepted.

### Keeping the benchmark from going stale

- **The benchmark is the 420 training lines with corrected labels.** The labels are corrected where the item is certain (section 4), so a change is never judged against a label that is wrong.
- **A growing set of new lines is always added.** New lines come from production and are labelled the same way: corrected only where the item is certain, and lines that are under-specified are not given an item (section 4). The 420 lines stay as they are, so every change is still compared on the same lines as before.
- **When new data arrives, the calibration and the fuzzy success line are re-learned.** The confidence values and the fuzzy line of 70 were measured on 420 lines; with more and more varied lines they are measured again, still with the 92.7% rule and its lower bound. The new values have to pass the same gates before they are used.
- **New patterns among the abstained lines are watched.** If the lines sent to a human start to look different, for example a new kind of mess the noise groups do not cover, or more lines falling back into the typo group, customers are writing in a way the matcher was not built for, and the benchmark no longer represents them.
