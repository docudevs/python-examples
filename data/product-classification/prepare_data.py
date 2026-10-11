"""Prepare the Open Food Facts sample used by notebook 10 (product classification).

Reads a random sample of the openfoodfacts/product-database Parquet export and the
Open Food Facts category taxonomy, builds a category tree whose labels are all leaves,
and splits the products into records and a held-out set. It writes three small files
next to this script:

    tree.json      category nodes for upload_tree
    records.csv    labelled records for bulk_upsert_records
    holdout.csv    held-out products with their true leaf code

Run from the repository root (needs pyarrow on top of the standard library):

    uv run --with pyarrow python data/product-classification/prepare_data.py

Downloads are cached in off-cache/ next to this script; the cache is gitignored.
See README.md in this directory for the data source and licence.
"""

import bisect
import csv
import io
import json
import random
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq

OUT_DIR = Path(__file__).resolve().parent
CACHE_DIR = OUT_DIR / "off-cache"

OFF_CATEGORIES = [
    "en:dairies",
    "en:sweet-snacks",
    "en:cereals-and-potatoes",
    "en:beverages",
    "en:frozen-foods",
    "en:sauces",
]
RG_SAMPLE = 60                 # row groups of the export to read (about 1.3% of its rows)
SAMPLE_SEED = 20261011
MIN_LEAF_PRODUCTS = 10         # categories with fewer products are rolled up to their parent
RECORDS_TARGET = 2500          # records in the knowledge base
HOLDOUT_TARGET = 100           # held-out products that get classified

HF_EXPORT_URL = "https://huggingface.co/datasets/openfoodfacts/product-database/resolve/main/food.parquet"
OFF_TAXONOMY_URL = "https://static.openfoodfacts.org/data/taxonomies/categories.json"
USER_AGENT = "docudevs-python-examples/1.0 (+https://github.com/docudevs/python-examples)"
NEEDED_COLUMNS = [
    "code",
    "product_name",
    "generic_name",
    "brands",
    "quantity",
    "ingredients_text",
    "categories_tags",
]
TEXT_COLUMNS = ("name", "generic_name", "brand", "quantity", "ingredients")
RECORD_COLUMNS = (*TEXT_COLUMNS, "ean", "leaf")


class PrefetchedRangeFile(io.RawIOBase):
    """Read-only file over HTTP range requests. Byte spans are downloaded in parallel first."""

    def __init__(self, url):
        self.url = url
        self.size = self._head_size()
        self.pos = 0
        self.bytes_downloaded = 0
        self._starts = []
        self._spans = []

    def _head_size(self):
        request = urllib.request.Request(self.url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            return int(response.headers["Content-Length"])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = {0: 0, 1: self.pos, 2: self.size}[whence] + offset
        return self.pos

    def _fetch(self, start, end, attempts=3):
        request = urllib.request.Request(
            self.url, headers={"Range": f"bytes={start}-{end - 1}", "User-Agent": USER_AGENT}
        )
        for attempt in range(1, attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    data = response.read()
                break
            except urllib.error.URLError:
                if attempt == attempts:
                    raise
                time.sleep(2 * attempt)
        assert len(data) == end - start, (start, end, len(data))
        self.bytes_downloaded += len(data)
        return data

    def prefetch(self, spans, workers=16):
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        with ThreadPoolExecutor(max_workers=workers) as pool:
            fetched = pool.map(lambda span: self._fetch(*span), [tuple(span) for span in merged])
            for (start, _), data in zip(merged, fetched):
                self._spans.append((start, data))
        self._spans.sort(key=lambda item: item[0])
        self._starts = [start for start, _ in self._spans]

    def _lookup(self, start, end):
        index = bisect.bisect_right(self._starts, start) - 1
        if index >= 0:
            span_start, data = self._spans[index]
            if end <= span_start + len(data):
                return data[start - span_start:end - span_start]
        return self._fetch(start, end)

    def read(self, size=-1):
        if size is None or size < 0:
            size = self.size - self.pos
        end = min(self.pos + size, self.size)
        if end <= self.pos:
            return b""
        data = self._lookup(self.pos, end)
        self.pos = end
        return data

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def column_spans(metadata, row_group, names):
    """Byte spans of the column chunks of one row group whose top-level column is in names."""
    group = metadata.row_group(row_group)
    spans = []
    for index in range(group.num_columns):
        column = group.column(index)
        if column.path_in_schema.split(".")[0] in names:
            start = column.dictionary_page_offset if column.has_dictionary_page else column.data_page_offset
            spans.append((start, start + column.total_compressed_size))
    return spans


def load_sample(cache_file):
    """Return the rows of RG_SAMPLE random row groups, reading only NEEDED_COLUMNS."""
    if cache_file.exists():
        return pq.read_table(cache_file).to_pylist(), 0
    handle = PrefetchedRangeFile(HF_EXPORT_URL)
    metadata = pq.read_metadata(handle)
    row_groups = sorted(random.Random(SAMPLE_SEED).sample(range(metadata.num_row_groups), RG_SAMPLE))
    spans = [span for rg in row_groups for span in column_spans(metadata, rg, set(NEEDED_COLUMNS))]
    handle.prefetch(spans)
    table = pq.ParquetFile(handle, metadata=metadata).read_row_groups(
        row_groups, columns=NEEDED_COLUMNS, use_threads=False
    )
    pq.write_table(table, cache_file)
    return table.to_pylist(), handle.bytes_downloaded


def load_taxonomy(cache_file):
    if not cache_file.exists():
        request = urllib.request.Request(OFF_TAXONOMY_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=300) as response:
            cache_file.write_bytes(response.read())
    return json.loads(cache_file.read_text(encoding="utf-8"))


def single_chain(tag, parents):
    """Return [root, ..., tag] if every step up has exactly one parent, otherwise None."""
    if tag not in parents:
        return None
    chain = [tag]
    while parents[chain[-1]]:
        if len(parents[chain[-1]]) > 1:
            return None
        parent = parents[chain[-1]][0]
        if parent in chain or parent not in parents:
            return None
        chain.append(parent)
    return list(reversed(chain))


def most_specific_chain(tags, parents, popularity):
    """The deepest category with an unambiguous path to a root; ties go to the more common one."""
    chains = [chain for chain in (single_chain(tag, parents) for tag in tags) if chain]
    if not chains:
        return None
    return max(chains, key=lambda chain: (len(chain), popularity.get(chain[-1], 0), chain[-1]))


def parents_from_taxonomy(taxonomy):
    return {tag: list(entry.get("parents") or []) for tag, entry in taxonomy.items()}


def category_name(tag, taxonomy):
    names = (taxonomy.get(tag) or {}).get("name") or {}
    return names.get("en") or tag.split(":", 1)[-1].replace("-", " ").capitalize()


def pick_text(entries):
    entries = entries or []
    for entry in entries:
        if entry.get("lang") == "en" and entry.get("text"):
            return clean_text(entry["text"])
    for entry in entries:
        if entry.get("text"):
            return clean_text(entry["text"])
    return ""


def clean_text(text):
    """Strip the text and use LF line ends, so git's autocrlf settings do not change the CSV."""
    return text.replace("\r\n", "\n").strip()


def normalise_product(raw):
    code = str(raw.get("code") or "").strip()
    name = pick_text(raw.get("product_name"))[:200]
    if not code or not name:
        return None
    return {
        "ean": code,
        "name": name,
        "generic_name": pick_text(raw.get("generic_name"))[:200],
        "brand": (raw.get("brands") or "").split(",")[0].strip()[:100],
        "quantity": (raw.get("quantity") or "").strip()[:100],
        "ingredients": pick_text(raw.get("ingredients_text"))[:300],
        "categories_tags": list(raw.get("categories_tags") or []),
    }


def unique_products(raw_products):
    products = {}
    for raw in raw_products:
        product = normalise_product(raw)
        if product and product["ean"] not in products:
            products[product["ean"]] = product
    return list(products.values())


def chains_by_ean(products, parents, popularity):
    """Leaf chains of the products. A product whose deepest category is a root is not labelled."""
    chains = {}
    for product in products:
        chain = most_specific_chain(product["categories_tags"], parents, popularity)
        if chain and len(chain) > 1:
            chains[product["ean"]] = chain
    return chains


def roll_up(chains, min_products):
    """Move products of a category with fewer than min_products direct products to its parent."""
    labels = dict(chains)
    deepest = max((len(chain) for chain in labels.values()), default=0)
    for depth in range(deepest, 0, -1):
        counts = Counter(chain[-1] for chain in labels.values() if len(chain) == depth)
        small = {tag for tag, count in counts.items() if count < min_products}
        for ean, chain in list(labels.items()):
            if len(chain) == depth and chain[-1] in small:
                labels[ean] = chain[:-1]
    return {ean: chain for ean, chain in labels.items() if chain}


def prune_to_leaves(chains, min_products):
    """Drop products until every remaining label is a leaf with enough products.

    A category with fewer than min_products products is removed, and so is a product whose
    category is an ancestor of another kept category (it would be a non-leaf label).
    Repeat until nothing changes, because each removal can expose another.
    """
    kept = dict(chains)
    while True:
        counts = Counter(chain[-1] for chain in kept.values())
        ancestors = {tag for chain in kept.values() for tag in chain[:-1]}
        dropped = [
            ean
            for ean, chain in kept.items()
            if counts[chain[-1]] < min_products or chain[-1] in ancestors
        ]
        if not dropped:
            return kept
        for ean in dropped:
            del kept[ean]


def build_tree(chains, taxonomy):
    """Build dotted-code tree nodes from leaf chains. Returns (nodes, code_of_tag)."""
    parent_of = {}
    for chain in chains.values():
        for parent, child in zip(chain, chain[1:]):
            parent_of[child] = parent
    tags = {tag for chain in chains.values() for tag in chain}
    children = defaultdict(list)
    for child, parent in parent_of.items():
        children[parent].append(child)
    roots = sorted(
        (tag for tag in tags if tag not in parent_of),
        key=lambda tag: category_name(tag, taxonomy),
    )
    code_of = {}
    nodes = []
    queue = [(tag, str(index), None) for index, tag in enumerate(roots, start=1)]
    while queue:
        tag, code, parent = queue.pop(0)
        code_of[tag] = code
        nodes.append({"code": code, "parent": parent, "name": category_name(tag, taxonomy)})
        kids = sorted(children[tag], key=lambda kid: category_name(kid, taxonomy))
        queue.extend((kid, f"{code}.{index}", code) for index, kid in enumerate(kids, start=1))
    return nodes, code_of


def group_key(product):
    if product["brand"]:
        return "brand:" + product["brand"].lower()
    words = product["name"].lower().split()
    return "name:" + (words[0] if words else product["ean"])


def split_records_and_holdout(products, records_target, holdout_target, seed):
    """Move whole brand groups (or name-word groups) to the holdout, so no group is on both sides."""
    groups = defaultdict(list)
    for product in products:
        groups[group_key(product)].append(product)
    keys = sorted(groups)
    random.Random(seed).shuffle(keys)
    held = set()
    holdout = []
    for key in keys:
        if len(holdout) >= holdout_target:
            break
        if len(holdout) + len(groups[key]) <= holdout_target:
            held.add(key)
            holdout.extend(groups[key])
    rest = [product for key in sorted(groups) if key not in held for product in groups[key]]
    random.Random(seed + 1).shuffle(rest)
    return rest[:records_target], holdout


def record_row(product, leaf_code):
    row = {column: product[column] for column in TEXT_COLUMNS}
    row.update({"ean": product["ean"], "leaf": leaf_code})
    return row


def level_fanout(nodes, leaves, max_depth):
    children = defaultdict(int)
    for node in nodes:
        if node["parent"]:
            children[node["parent"]] += 1
    rows = []
    for depth in range(1, max_depth + 1):
        at_depth = [node for node in nodes if len(node["code"].split(".")) == depth]
        leaves_here = [node for node in at_depth if node["code"] in leaves]
        internal = [node for node in at_depth if node["code"] not in leaves]
        mean = sum(children[node["code"]] for node in internal) / len(internal) if internal else 0
        rows.append((depth, len(at_depth), len(leaves_here), round(mean, 1)))
    return rows


def write_outputs(nodes, records_rows, holdout_rows):
    (OUT_DIR / "tree.json").write_text(json.dumps(nodes, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, rows in (("records.csv", records_rows), ("holdout.csv", holdout_rows)):
        with (OUT_DIR / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RECORD_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {OUT_DIR / name} ({len(rows):,} rows)")
    print(f"Wrote {OUT_DIR / 'tree.json'} ({len(nodes)} nodes)")


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    taxonomy = load_taxonomy(CACHE_DIR / "categories.json")
    parents = parents_from_taxonomy(taxonomy)
    print(f"Taxonomy: {len(parents):,} categories")

    sample_file = CACHE_DIR / f"sample-rg{RG_SAMPLE}-seed{SAMPLE_SEED}.parquet"
    sample_rows, downloaded_bytes = load_sample(sample_file)
    if downloaded_bytes:
        print(f"Downloaded {downloaded_bytes / 1e6:.1f} MB of column data from the Parquet export")
    else:
        print(f"Loaded the cached sample {sample_file}")

    wanted = set(OFF_CATEGORIES)
    matched = [row for row in sample_rows if wanted & set(row["categories_tags"] or [])]
    products = unique_products(matched)
    print(f"Sample: {len(sample_rows):,} products in {RG_SAMPLE} row groups")
    print(f"In the chosen categories: {len(matched):,} rows, {len(products):,} unique products")

    popularity = Counter(tag for product in products for tag in set(product["categories_tags"]))
    chains = chains_by_ean(products, parents, popularity)
    print(f"Products with a deepest category below a root: {len(chains):,}")
    depths = Counter(len(chain) for chain in chains.values())
    print("Depth of each product's most specific category (levels):")
    for depth in sorted(depths):
        print(f"  {depth}: {depths[depth]:,}")

    print("\nExamples:")
    for product in products[:3]:
        chain = chains.get(product["ean"])
        path = " > ".join(category_name(tag, taxonomy) for tag in chain) if chain else "(no sub-category)"
        print(f"- {product['name']} | brand: {product['brand'] or '-'} | {product['quantity'] or '-'}")
        print(f"  {path}")

    rolled = roll_up(chains, MIN_LEAF_PRODUCTS)
    kept_chains = {ean: chain for ean, chain in prune_to_leaves(rolled, MIN_LEAF_PRODUCTS).items() if len(chain) > 1}
    nodes, code_of = build_tree(kept_chains, taxonomy)
    leaves = sorted({code_of[chain[-1]] for chain in kept_chains.values()})
    leaf_of = {ean: code_of[chain[-1]] for ean, chain in kept_chains.items()}
    max_depth = max(len(code.split(".")) for code in leaves)
    leaf_sizes = Counter(leaf_of.values())
    print(f"Rolled up: {len(chains) - len(rolled):,} products moved to a parent category")
    print(f"Pruned: {len(rolled) - len(kept_chains):,} products dropped to keep every label a leaf")
    print(f"Tree: {len(nodes)} categories, {len(leaves)} leaves, depth {max_depth}")
    print(f"Products kept: {len(kept_chains):,}")
    print("Largest leaves:")
    for code, count in leaf_sizes.most_common(5):
        name = next(node["name"] for node in nodes if node["code"] == code)
        print(f"  {code:10} {name} ({count})")

    kept_products = [product for product in products if product["ean"] in kept_chains]
    records_pool, holdout_pool = split_records_and_holdout(
        kept_products,
        RECORDS_TARGET,
        HOLDOUT_TARGET,
        seed=SAMPLE_SEED,
    )
    records_leaves = {leaf_of[product["ean"]] for product in records_pool}
    holdout = [product for product in holdout_pool if leaf_of[product["ean"]] in records_leaves]
    records_rows = [record_row(product, leaf_of[product["ean"]]) for product in records_pool]
    holdout_rows = [record_row(product, leaf_of[product["ean"]]) for product in holdout]
    print(f"Records: {len(records_rows):,} products in {len(records_leaves)} leaves")
    print(f"Holdout: {len(holdout)} products from brands that are not in the records")

    print("Level  categories  leaves  mean children (internal nodes)")
    for depth, total, leaf_count, mean in level_fanout(nodes, leaves, max_depth):
        print(f"{depth:>5}  {total:>10}  {leaf_count:>6}  {mean:>10}")
    leaf_counts = sorted(leaf_sizes.values())
    print(f"Products per leaf: min {leaf_counts[0]}, median {leaf_counts[len(leaf_counts) // 2]}, max {leaf_counts[-1]}")

    write_outputs(nodes, records_rows, holdout_rows)


if __name__ == "__main__":
    main()
