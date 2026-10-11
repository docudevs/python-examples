# Product classification data (notebook 10)

Small derived extract of [Open Food Facts](https://world.openfoodfacts.org) products, used by
[`10-product-classification.ipynb`](../../10-product-classification.ipynb). The notebook reads these
files directly, and `prepare_data.py` regenerates them.

## Files

| File | Rows | Size | Contents |
|------|------|------|----------|
| `tree.json` | 165 nodes | 14 KB | Category tree: `code` (dotted, e.g. `1.2.6`), `parent` (code or `null` for a root), `name` (English). |
| `records.csv` | 2,500 | 436 KB | Labelled records: `name`, `generic_name`, `brand`, `quantity`, `ingredients`, `ean`, and `leaf` (the leaf code of the category, e.g. `1.2.6`). |
| `holdout.csv` | 100 | 16 KB | Held-out products with the same columns. `leaf` is the true label used for accuracy. Holdout brands do not appear in `records.csv`. |

The tree has 94 leaves (labels) and depth 8. Text fields are truncated: names and generic names to
200 characters, ingredients to 300, quantity to 100, brand to 100.

## How the files were produced

```bash
uv run --with pyarrow python data/product-classification/prepare_data.py
```

The script (`prepare_data.py`) runs these steps:

1. Reads the Open Food Facts category taxonomy (`categories.json`).
2. Reads a random sample of the Parquet export (`food.parquet` on Hugging Face) with HTTP range
   requests, downloading only the needed columns of the sampled row groups.
3. Keeps products in six categories (dairies, sweet snacks, cereals and potatoes, beverages,
   frozen foods, sauces), takes each product's most specific category with a single path to a root,
   and rolls up or prunes categories with fewer than 10 products so every label is a leaf.
4. Splits products into records and holdout by brand group, so no brand is on both sides.

Knobs are constants at the top of the script: `OFF_CATEGORIES`, `RG_SAMPLE` (60 row groups),
`SAMPLE_SEED` (20261011), `MIN_LEAF_PRODUCTS` (10), `RECORDS_TARGET` (2,500) and `HOLDOUT_TARGET`
(100). The downloads are cached in `off-cache/` next to the script, which is gitignored. The first
run downloads about 115 MB; later runs use the cache. `pyarrow` is needed only to run the script,
not the notebook.

The sample covers all countries. The data is a sample of the whole export, not a complete extract of
any one market.

## Attribution

Data from [Open Food Facts](https://world.openfoodfacts.org), via the
[openfoodfacts/product-database](https://huggingface.co/datasets/openfoodfacts/product-database)
export on Hugging Face.

The files in this directory are a derived extract of the Open Food Facts database and are made
available under the [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
The individual contents of the database are made available under the
[Database Contents License (DbCL) 1.0](https://opendatacommons.org/licenses/dbcl/1-0/).
Suggested attribution: *"Contains data from Open Food Facts, available under the Open Database License."*

The repository's MIT licence does not apply to these data files. `prepare_data.py` is code and is under the repository's MIT licence. The full notice is in [`LICENSE`](LICENSE).
