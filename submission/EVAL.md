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

To be written.

## 3. Error analysis

To be written.

## 4. The label problem

To be written.

## 5. Regression safety

To be written.
