1. Objective Function

Decision Variables:
x = number of correct auto-matches (each saves the operator 20 seconds)
y = number of abstentions sent to a human (each costs 40 seconds)
z = number of wrong auto-matches (each costs 800 seconds, which is 20 times an abstention)

Objective Function:
Maximize Z = 20x - 40y - 800z

This is the function constructed to maximize the time that we can save.

Constraints:
x >= 0, y >= 0, z >= 0
x + y + z = Total
x >= 12.67 * z

Another constraint, to make this more precise, comes from finding the point where auto-answering and abstaining are equal. Let p be the probability that an auto-answer is correct.
Auto-answer: 20p - 800(1 - p) = 820p - 800
Abstain: -40 (constant, whatever p is)
The two are equal when 820p - 800 = -40, so p = 0.9268.
Above this p, auto-answering saves more than abstaining. Below it, abstaining is the better choice. Based on this we can construct the constraint on precision.

Operating point:
The constraints form a triangle (the feasible region). Its three corners are:
O = (x = 0, y = Total, z = 0): every line sent to a human
A = (x = Total, y = 0, z = 0): every line a correct auto-match
C = (x = 0.927 * Total, y = 0, z = 0.073 * Total): the break-even point

Any operating point inside the triangle is acceptable, because it saves more time than sending every line to a human. Along the edge from O to C it is exactly break-even. We choose the point nearest A that the matcher can actually achieve.

Who gets to move it:
The project manager decides the coverage, meaning how much of the work should be automated. This is a business decision, so the project manager does not need the technical details. Before moving it, the project manager discusses it with the customer's manager and the engineer to reach consensus. In that discussion the engineer explains whether the requested coverage can be met while staying inside the triangle. The engineer then sets the operating point inside the triangle to meet that coverage. The project manager is accountable for the consequences of the decision, and the engineer is accountable if the point is set wrongly.

2. Pipeline

Every search only looks in the catalogue of the line's own tenant. Frozen food and hardware are completely separate, so a line can never be matched to the other tenant's items.

New tenant (cold start):
A new tenant only needs its catalogue. The matcher loads every tenant's catalogue the same way, so all the stages (barcode, exact name, fuzzy and embeddings) work for it from day one. The difference is the buyer SKU lookup: a new tenant has no SKU map yet, so that lookup finds nothing, and more of its lines go to fuzzy matching or to a human. As reviewers confirm items, the SKU map builds up and the tenant behaves more like a mature one. On the training lines, the SKU map gave 63 of the 309 automatic answers.

Before searching, two kinds of catalogue rows are removed:
- Junk rows: DELIVERY FEE, MISC CHARGE, OPENING BALANCE and SAMPLE - DO NOT SELL. Their codes contain MISC, they have empty fields and a price of 0, and they are not real products, so they are dropped. A line that only says something like "delivery fee" is not a product order, so it should never be matched to an item.
- Old items, with codes ending in -OLD and marked disabled. They have been replaced, so they are dropped. If a buyer's SKU still points to an old item, the match is switched to its replacement, which has the same code without -OLD.

Stage 0: Normalization (deterministic)
Before any matching, the line is lowercased and cleaned using four short lists, all taken from words that actually appear in the order lines:
- Abbreviations are expanded: S/S to stainless, ZP to zinc plated, FC to full cream, and "inch" to ". SS304 is left as it is, because the catalogue itself writes SS304 in many item names.
- Known Malay words are translated into English, for example skru to screw, susu to milk, paip to pipe, pita to tape, mentega to butter and "topi keledar" to helmet.
- Known filler words used by customers are removed: pls, please, need, send, item, kindly, thanks, bro and urgent.
- Quantity and packing words are removed: ctn, carton, case, box, pack and pkt, plus an "x + number" left at the end of the line (see failure mode 1 in section 4). "kg" is not removed, because it is part of item names such as "Prawn 1kg".
Separators become spaces: slashes and spaced dashes used between words ("Kanto/Self/Drilling/Screw", "KANTO - SELF - DRILLING"), colons ("item:") and list numbering at the start ("1)"). Symbols that carry meaning are kept: " for inches (two single quotes '' are turned into "), # for screw sizes, fractions like 3/4, ranges like 19-25mm, and x in dimensions like M8x75.
A missed abbreviation, Malay word or filler word is not dangerous: it only lowers the fuzzy score, so the line moves on to embeddings or a human. The lists are a shortcut for words already seen, not a complete dictionary.
Every later stage works on the cleaned line.

Stage 1: Regex (deterministic)
Looks for an exact item name, SKU code or barcode in the line. If something is captured, it is looked up in the tenant's catalogue CSV. If regex finds nothing, the line is passed to fuzzy matching.
A barcode is taken from the barcode field first, then from any 8 to 14 digit number typed inside the line, so a barcode pasted into the text is still captured.
A buyer's own SKU is looked up in the buyer SKU map for that tenant and that customer only. Mappings whose end date (valid_to) is before the order date are ignored, because some customers' numbers were moved to a different item. In this data every end date (2026-03-31) is before every order (from 2026-04-01), so any mapping with an end date is skipped when the map is loaded. In production this would be checked against each order's date instead. Which mappings are trusted is described in failure mode 5 (section 4).

Stage 2: Fuzzy matching (deterministic)
Compares the cleaned line against every cleaned item name in the tenant's catalogue using rapidfuzz's ratio score (characters in common, in order, compared with the length of both texts), and keeps the top 3. Plain ratio was chosen after testing four scorers on the training lines: it picked the right item most often and gave the fewest high scores to lines that should be abstained. Scorers that ignore extra words gave vague lines like "kanto" a perfect score against any Kanto item.
Fuzzy always finds look-alikes, so two checks send the line to a human even when the top score is high:
- Gap check: the second-best candidate is within 1 point of the best. Typos that change a number create exactly this kind of tie, for example "3700mm" scores the same against the 300mm and 370mm cable ties.
- Word check: more than one catalogue item contains every word of the line, for example "Tolsen Hex Bolt M8x50" fits the HDG, Zinc Plated, Stainless 304 and Stainless 316 versions. The ratio score alone misses this, because longer names score lower even when they fit the line just as well.
If neither check fails, the score falls into one of three zones (below).

Stage 3: Embeddings (probabilistic)
Only runs when the fuzzy score is in the failure zone. It returns its top 3 candidates as suggestions for the reviewer, and only answers on its own once it reaches the 92.7% success line (section 3).

Unique Item Names:
No two items have exactly the same name. Some names have the same text but a different number at the end, and that number is a different spec, for example "Sisu Beef Patty 150g 12s", "24s" and "48s". A few use "(Bulk)" at the end in the same way, such as "Vermont PVC Pipe 50mm Class D (Bulk)". If the line includes that number, it is used to pick the right item. If the line leaves it out, several items match equally well, so the line is sent to a human. This also applies to exact name matches: if other items extend the matched name (for example with "(Bulk)"), the line goes to a human with all of them as candidates.

Confidence zones:
- Success (92.7% and above): fuzzy returns the answer; embeddings return the answer.
- Unsure: fuzzy sends the line to a human; embeddings send the line to a human.
- Failure: fuzzy passes the line to embeddings; embeddings send the line to a human.

The success zone starts at 92.7% because of the break-even in section 1: below that, sending the line to a human saves more time.
92.7% is a precision, not a raw score, so the raw score that delivers it is measured on the training lines. For fuzzy, the success line is the lowest ratio score at which a 95% lower bound on precision (for fuzzy answers that pass both checks) still clears 92.7%. On the training lines that is 70: 67 answers, 66 of them correct, with a lower bound of 93.6%. The lower bound accounts for the small sample, so a cut-off backed by fewer answers needs to look better to qualify. This is re-measured in Task 3.
The line between unsure and failure is not fixed yet. Once the matcher exists, we build an ROC curve from the data, and the team (project manager, customer's manager and engineer, as in section 1) decides where to place it.

Why this order:
Regex is fast and needs very little computation. Embeddings need more calculation, so they are slower and cost more. So the cheap stages run first, and embeddings only run when they are needed.

Why unsure goes to a human and failure goes to embeddings:
If fuzzy is unsure, it has already found similar words, so embeddings would most likely find the same candidates. Running them would be extra work with no benefit.
If the fuzzy score is very low, the words in the line do not overlap with the catalogue at all, for example a Malay word that is not in the stage 0 list. Fuzzy compares characters, so it cannot connect these. Embeddings compare meaning, so this is where they can still find a match.

3. Where an LLM or Embeddings Earn Their Place

Embeddings:
Embeddings are used in one place only: stage 3 of the pipeline. The cheaper methods are tried first: regex for exact codes and names, then fuzzy matching for typos. Embeddings only run when fuzzy finds no overlap in words. That is where they add something, because they compare meaning and can match a line written with different words. The Malay words already seen in the order lines (such as "skru" for screw and "susu" for milk) are translated in stage 0. We use a multilingual local model, so Malay words that are not on that list are still understood. Trade abbreviations such as S/S and ZP are also expanded in stage 0, so the model does not need to know them.

Fallback when the model is unavailable or slow:
The model runs locally, so outages are rare, but it can still fail to load or run out of memory. If the embedding stage errors, or the model is not on the machine, the line is sent to a human.
There is no time limit per line. A limit would make the answer depend on how fast the machine is, and the matcher must give the same answer for the same input. Instead, the time per line is measured and reported, and checked against the 250 ms budget.

When the model is wrong:
- Calibrate the score. An embedding's similarity score is not a probability. Using the labelled data, we check how often each score level is actually right, and the 92.7% rule from section 1 is applied to that measured figure, not to the raw score. Until the labelled answers prove it, embeddings never answer on their own: even with every answer right, it takes 35 of them before the lower bound clears 92.7%. The training lines have none, so for now embeddings only suggest candidates.
- Word check. As in fuzzy, if more than one catalogue item contains every word of the line, the line goes to a human. For example "40mm class" fits 23 pipes of different brands and classes.
- Gap check. If the best and second-best candidates score almost the same, the model cannot tell them apart, so the line goes to a human, even if the top score is high.
- Hard-detail check. If the line names a brand or a size, the candidate must contain them too. Embeddings judge overall meaning, so they can pick the wrong brand or size, and a simple text check catches this.
- The unique item names rule from section 2 applies here too. Embeddings cannot tell specs apart well, so if the number is missing from the line, it goes to a human.

LLM:
We do not use an LLM. The reasons:
1. The stages already cover what an LLM would do. Regex handles exact codes, fuzzy handles typos, and embeddings handle meaning and other languages. The hard cases that are left already go to a human, which costs 40 seconds, while a wrong LLM answer can cost 800.
2. The design depends on an honest confidence score that is compared against 92.7%. An LLM gives a fluent answer, not a trustworthy probability, so it does not fit the decision rule.
3. Even a local LLM needs far more computation than embeddings.
4. An LLM can invent an item code that does not exist.

The one kind of line embeddings cannot handle is a reference to a past order, such as "same as last week's order". An LLM cannot handle it either, because the answer is in the customer's order history, not in the text. These lines are abstained and go to a human.

4. Failure Modes

These are the six most expensive ways the system can be confidently wrong on this data, meaning it auto-answers and the answer is wrong.

1. A quantity is read as part of the product name
Example: in "x24 ctn" the 24 is a quantity or pack size, but it can be mistaken for part of a name like "Beef Patty 24s".
Mechanism: in stage 0, a list of unit words (ctn, carton, case, box, pack, pkt) and the "x + number" pattern are used to take these out of the text used for matching. "x + number" is only removed when it is at the end of the line or followed by a unit word. It is kept when it is followed by an inch mark (x 2") or sits between two numbers (M8x75), because then it is a spec. The real order quantity is already in the line's qty and uom_text columns.

2. Embeddings do not recognise the brand
Example: a "Hitex cable tie" line is matched to a Tolsen cable tie, because embeddings judge overall meaning.
Mechanism: the hard-detail check from section 3. If the line names a brand, the candidate must contain it, otherwise the line goes to a human.

3. Abbreviations are missing from the list or expanded in the wrong place
Example: SDS is mentioned in the brief but is not in the list yet, and "pls/send" contains "s/s" across two words.
Mechanism: an abbreviation is only expanded when it is not touching other letters on either side (a space, slash, dash, or the start or end of the line), and the abbreviation list is extended when new ones are found in the order lines.

4. Over-reliance on confidence scores
Example: the design trusts that a score of 92.7% or above means the answer is right. If the scores are not honest, every auto-answer is overconfident at the same time.
Mechanism: the scores are calibrated on the labelled data, as in section 3, so that 92.7% really means 92.7% correct.

5. A wrong match is saved and repeated
Example: the system wrongly matches "Hitex cable tie 150mm" to a Tolsen cable tie and saves it as a mapping. Next time the same line comes in, it is found as an exact match and sent again with full confidence.
Mechanism:
- Assumption: mappings with source confirmed_order or manual_import are treated as accurate regardless of their confidence value, once expired mappings are removed (see section 2).
- inferred_match mappings are guesses. If the confidence is 1.0, the buyer's SKU is replaced with the mapped item code. If it is below 1.0, the link is not trusted: the buyer's SKU is replaced with the mapping's description instead, and that text goes through fuzzy matching and embeddings like the rest of the line, so related items can still be suggested.
- New mappings are only saved after a person confirms them, for example when a reviewer picks the item in the review queue. A mapping is removed if it causes a return or a credit note.

6. A typo makes the item name come out wrong
Example: "Tolsen Cablle Tie 3700mm White", where the correct item is 370mm. If fuzzy cannot resolve the line at all, it moves on safely. The danger is when the typo still looks like a real item and fuzzy gives it a high score.
Mechanism: the gap check in stage 2. A typo that changes a number makes several sizes score the same ("3700mm" ties 300mm and 370mm; "05mm" ties 15, 20, 25 and 40mm), so the line goes to a human.
A whole-number check was also tested on the training lines and dropped: every bad answer it caught was already caught by the gap check, and on its own it sent 7 correct answers to review (for example "16/0" for 16/20). A price check was not added: after the gap and word checks, the only bad high-scoring answer left on the training lines is one we believe is mislabelled, so there was nothing left for it to catch.

5. Boundary

Out of scope for 3 days:
1. Saving confirmed orders. When a reviewer confirms the right item for a line, that line and its item are saved, so the same line is recognised as an exact match next time. Failure mode 5 in section 4 describes the rules: only confirmed answers are saved, and a saved answer that causes a return or credit note is removed. Building this needs real reviewer decisions and return data, which do not exist yet.
2. Quantity conversion. Stage 0 removes quantity and pack wording like "x24 ctn" so it does not confuse matching, but converting the ordered quantity into stock units using uom_reference is not built.
3. The review process. When a line is abstained, the pipeline only hands it off to the review queue and records it. The review queue itself, and what the reviewer does with the line, is not part of this build.

What we would need to see in production before building more:
1. Request traffic. We need to know how many order lines arrive at the same time, including the peaks, such as busy hours or the end of the month when many customers order at once. We also need to know what share of those lines get as far as stage 3, because embeddings are the slowest stage and only the lines that fuzzy cannot resolve reach it, and how long the embedding stage takes per line when it is busy. Together these numbers decide the architecture, for example how many pods are needed so that a peak does not slow every order down.
2. Embeddings accuracy. Embeddings are kept because they should resolve lines that fuzzy cannot, but they also add their own mistakes. To measure this safely, the embedding stage first runs in shadow mode: it still runs on every line that reaches stage 3 and records the item it would have picked, but its answer is not used, and the line goes to a human as if embeddings were not there. Comparing what embeddings would have picked with what the reviewer actually chose shows how often they are right, without any wrong item being shipped. Using the costs from section 1, a correct answer gains 60 seconds compared with sending the line to a human (+20 instead of -40), while a wrong answer loses 760 (-800 instead of -40), so one mistake cancels out about 12.7 correct answers, the same ratio as the precision constraint in section 1. Only if shadow mode shows embeddings staying above that ratio are their answers switched on. If not, the stage is removed.
