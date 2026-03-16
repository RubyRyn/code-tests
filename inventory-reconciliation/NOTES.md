# Inventory Reconciliation — Notes

## Approach

I started with exploratory data analysis in a Jupyter notebook (`ExploratoryDataAnalysis.ipynb`) before writing any reconciliation logic. The goal was to understand the shape, quality, and quirks of both snapshots so the reconciliation script could handle real-world messiness rather than assuming clean inputs. Every data quality issue discovered in EDA directly informed a cleaning step or validation check in `reconcile.py`.

## EDA Process

The EDA notebook walked through the data systematically:

1. **Schema inspection** — Loaded both CSVs and immediately noticed the column names don't match. Snapshot 1 uses `name`, `quantity`, `location`, `last_counted` while snapshot 2 uses `product_name`, `qty`, `warehouse`, `updated_at`. This would silently break any merge without a column mapping step.

2. **Data types** — Snapshot 1's `quantity` is `int64`, snapshot 2's `qty` is `float64` (values like `70.0`, `80.00`). The date columns loaded as `object` (strings) in both. These mismatches needed normalization before comparison.

3. **SKU validation** — Checked length consistency, case consistency, whitespace, hidden characters, uniqueness, and format pattern across both datasets.

4. **Null and disguised null checks** — Scanned for actual nulls and string placeholders like `"N/A"`, `"None"`, `"-"`.

5. **Duplicate detection** — Found a key duplicate in snapshot 2 (same SKU, different data).

6. **Date validation** — Checked parseability and found mixed date formats in snapshot 2.

7. **Cross-snapshot consistency** — Merged on SKU to compare product names between snapshots and found a naming discrepancy.

8. **Basic statistics and distributions** — Used `describe()` and histograms to spot outliers, including a negative quantity value.

## Data Quality Issues Found

| Issue | Count | Case |
|---|---|---|
| Column name mismatch between snapshots | 4 | `name` vs `product_name`, `qty` vs `quantity` |
| Non-standard SKU format (missing dash) | 2 | `SKU005` → `SKU-005`, `SKU018` → `SKU-018` |
| Case inconsistency in SKU | 1 | `sku-008` → `SKU-008` |
| Leading/trailing whitespace in product name | 5 | `" Widget B"`, `"Mounting Bracket Large "`, `" HDMI Cable 3ft "`, `" Compressed Air Can"` |
| Negative quantity | 1 | SKU-045 has qty `-5` (second duplicate row) |
| Non-ISO date format | 1 | `01/15/2024` on SKU-035 in snapshot 2 |
| Duplicate SKU | 1 | SKU-045 appears twice in snapshot 2 with different names and quantities |
| Product name mismatch (same SKU, different name) | 1 | `Multimeter Pro` → `Multimeter Professional` |
| Quantity dtype mismatch | — | `int64` in snapshot 1, `float64` in snapshot 2 |
| SKU whitespace | 0 | Clean in both datasets |
| SKU hidden characters | 0 | Clean in both datasets |

## How Issues Were Fixed (and Why)

**Column mapping** — Created a `COLUMN_MAPPING` dictionary that maps both schemas to a unified set of names. This is explicit, maintainable, and easy to update if future snapshots introduce new column names.

**SKU normalization** — Applied a multi-step cleaning pipeline: strip whitespace, remove hidden characters, uppercase everything, then regex-fix formatting issues like missing hyphens (`SKU005` → `SKU-005`). The order matters — whitespace and case must be handled before format validation, otherwise the regex won't match.

**Duplicate resolution** — For SKU-045 appearing twice in snapshot 2, we keep the row with the higher quantity as a safe default assumption. However, this is not necessarily the correct business rule. In production, the right approach is to understand the business context and consult the data owner — the duplicate could represent a correction, a return, a multi-location split, or a data entry error, and each scenario calls for a different resolution strategy. The decision is logged in the issues list so it can be revisited.

**Product name mapping** — Built a dynamic SKU-to-name mapping from both snapshots rather than hardcoding names, since new products may appear in snapshot 2 that don't exist in snapshot 1 (and vice versa for removed items). The mapping combines both datasets so it covers old and new products alike. For conflicts like `Multimeter Pro` vs `Multimeter Professional`, we default to preferring snapshot 1's name as a safe assumption — it's the established record. In production, this preference is easily configurable and should be aligned with the business rule (e.g., always use the latest name, or always defer to a master product catalog).

**Date parsing** — Used a multi-pass approach: let pandas guess first, then try explicit format strings (`%Y-%m-%d`, `%m/%d/%Y`, etc.) for anything still unparsed. This handles any mixed format issue without hardcoding assumptions about which rows use which format.

**Quantity normalization** — Coerced all quantities to numeric with `pd.to_numeric(errors='coerce')`, filling unparseable values with 0. This unifies the `int64`/`float64` mismatch and handles any stray strings.

## Reconciliation Logic

After cleaning both snapshots, the core reconciliation is a full outer merge on SKU. This ensures every item from both snapshots is represented — items only in snapshot 1, items only in snapshot 2, and items in both. Each row is then classified into one of five categories:

- **removed** — exists in snapshot 1 but not in snapshot 2 (item dropped from inventory entirely or out of stock probably)
- **added** — exists in snapshot 2 but not in snapshot 1 (new item introduced)
- **increased** — exists in both, quantity went up (restocking)
- **decreased** — exists in both, quantity went down (consumption or sales)
- **unchanged** — exists in both, same quantity

A `quantity_diff` column captures the numeric delta (after minus before), which is NaN for added/removed items since only one side has a value. 

For consolidated fields (product name, location, date), the report prefers the most current or authoritative value: snapshot 1's name (established record), snapshot 2's location (current state), and snapshot 2's date (most recent). The final report is sorted by change type severity (removed first, unchanged last) for quick scanning.

## Benefits of the EDA Notebook

The notebook serves as a living audit trail. Every issue discovered is documented with the code that found it, making the analysis reproducible and reviewable. It also decouples exploration from production logic — the notebook is for understanding the data, `reconcile.py` is for processing it. This separation means the script's cleaning steps aren't guesswork; each one traces back to a specific finding in EDA.

## AI Tooling

I used Claude as a thought partner throughout this project. During EDA, I discussed what checks to run for SKU validation, how to detect case inconsistencies, and how to handle mixed date formats. For the reconciliation script, I worked through design decisions and how to structure the merge and classification logic. For testing, Claude helped me think through edge cases like empty DataFrames and verify that my test coverage matched the actual function behavior. The code and decisions are my own, but the iterative back-and-forth helped me move faster and catch things I might have missed.