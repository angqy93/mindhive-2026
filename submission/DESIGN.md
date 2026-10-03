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

Before searching, two kinds of catalogue rows are removed:
- Junk rows: DELIVERY FEE, MISC CHARGE, OPENING BALANCE and SAMPLE - DO NOT SELL. Their codes contain MISC, they have empty fields and a price of 0, and they are not real products, so they are dropped. A line that only says something like "delivery fee" is not a product order, so it should never be matched to an item.
- Old items, with codes ending in -OLD and marked disabled. They have been replaced, so they are dropped. If a buyer's SKU still points to an old item, the match is switched to its replacement, which has the same code without -OLD.

Stage 0: Normalization (deterministic)
Before any matching, the line is cleaned:
- Abbreviations are expanded first, using a short hand-written list, for example S/S and SS304 to stainless steel, and ZP to zinc plated. This comes first because S/S contains a slash and would be lost if symbols were removed first.
- Slashes used as word separators are turned into spaces, for example "Kanto/Self/Drilling/Screw". Symbols that carry meaning are kept: " for inches, # for screw sizes, fractions like 3/4, and x in dimensions like M8x75.
Every later stage works on the cleaned line.

Stage 1: Regex (deterministic)
Looks for an exact item name, SKU code or barcode in the line. If something is captured, it is looked up in the tenant's catalogue CSV. If regex finds nothing, the line is passed to fuzzy matching.

Stage 2: Fuzzy matching (deterministic)
Compares the whole sentence against the tenant's catalogue. It always returns a best candidate with a confidence score, and the score falls into one of three zones (below).

Stage 3: Embeddings (probabilistic)
Only runs when the fuzzy score is in the failure zone. It also returns a best candidate with a confidence score.

Unique Item Names:
No two items have exactly the same name. Some names have the same text but a different number at the end, and that number is a different spec, for example "Sisu Beef Patty 150g 12s", "24s" and "48s". A few use "(Bulk)" at the end in the same way, such as "Vermont PVC Pipe 50mm Class D (Bulk)". If the line includes that number, it is used to pick the right item. If the line leaves it out, several items match equally well, so the line is sent to a human.

Confidence zones:
- Success (92.7% and above): fuzzy returns the answer; embeddings return the answer.
- Unsure: fuzzy sends the line to a human; embeddings send the line to a human.
- Failure: fuzzy passes the line to embeddings; embeddings send the line to a human.

The success zone starts at 92.7% because of the break-even in section 1: below that, sending the line to a human saves more time.
The line between unsure and failure is not fixed yet. Once the matcher exists, we build an ROC curve from the data, and the team (project manager, customer's manager and engineer, as in section 1) decides where to place it.

Why this order:
Regex is fast and needs very little computation. Embeddings need more calculation, so they are slower and cost more. So the cheap stages run first, and embeddings only run when they are needed.

Why unsure goes to a human and failure goes to embeddings:
If fuzzy is unsure, it has already found similar words, so embeddings would most likely find the same candidates. Running them would be extra work with no benefit.
If the fuzzy score is very low, the words in the line do not overlap with the catalogue at all, for example a Malay word like "susu" for milk. Fuzzy compares characters, so it cannot connect these. Embeddings compare meaning, so this is where they can still find a match.

3. Where an LLM or Embeddings Earn Their Place

Embeddings:
Embeddings are used in one place only: stage 3 of the pipeline. The cheaper methods are tried first: regex for exact codes and names, then fuzzy matching for typos. Embeddings only run when fuzzy finds no overlap in words. That is where they add something, because they compare meaning and can match a line written with different words. We use a multilingual local model, so it understands Malay and English together, for example "skru" for screw and "susu" for milk. Trade abbreviations such as S/S and ZP are already expanded in stage 0, so the model does not need to know them.

Fallback when the model is unavailable or slow:
The model runs locally, so outages are rare, but it can still fail to load or run out of memory. If the embedding stage errors, or takes longer than a set time limit, the line is sent to a human.

When the model is wrong:
- Calibrate the score. An embedding's similarity score is not a probability. Using the labelled data, we check how often each score level is actually right, and the 92.7% rule from section 1 is applied to that measured figure, not to the raw score.
- Gap check. If the best and second-best candidates score almost the same, the model cannot tell them apart, so the line goes to a human, even if the top score is high.
- Hard-detail check. If the line names a brand or a size, the candidate must contain them too. Embeddings judge overall meaning, so they can pick the wrong brand or size, and a simple text check catches this.
- The unique item names rule from section 2 applies here too. Embeddings cannot tell specs apart well, so if the number is missing from the line, it goes to a human.

LLM:
We do not use an LLM. The reasons:
1. The stages already cover what an LLM would do. Regex handles exact codes, fuzzy handles typos, and embeddings handle meaning and other languages. The hard cases that are left already go to a human, which costs 40 seconds, while a wrong LLM answer can cost 800.
2. The design depends on an honest confidence score that is compared against 92.7%. An LLM gives a fluent answer, not a trustworthy probability, so it does not fit the decision rule.
3. Even a local LLM needs far more computation than embeddings.
4. An LLM can invent an item code that does not exist.

The one kind of line embeddings cannot handle is a reference to a past order, such as "same as last week's order". An LLM cannot handle it either, because the answer is in the customer's order history, not in the text. These lines go to a human, and using order history is left out of scope (section 5).

4.

5.
