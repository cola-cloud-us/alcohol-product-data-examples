# Match your own alcohol UPC list to candidate approvals

Use a small set of products you know to evaluate the current COLA Cloud barcode endpoint. Start with a dry run, inspect the selected strings, then explicitly opt into account-backed lookup. This recipe makes at most **ten requests per invocation** and never retries automatically.

It uses Python 3.10+ and the standard library. The local validation stage needs no account or network. Lookup requires your existing `COLA_API_KEY` environment variable and an account with available API record quota. Do not put the key in the CSV, source code or a command-line argument.

## Prepare a CSV with text barcodes

Export a file with a column named `upc`, one value per row. You can include your own SKU/name columns; the recipe does not send or copy them. Use `--column barcode` if your identifier column has another name.

Keep UPC/EAN values as text, preserving leading zeros. Spreadsheet number conversion can permanently remove those zeros. This recipe rejects scientific notation, spaces, hyphens, Unicode numerals, empty/all-zero values, invalid check digits and lengths other than 12 or 13. It does not guess or repair the intended value. UPC-E, EAN-8 and 14-digit case identifiers are outside this starter recipe.

## Inspect a dry run

From this repository directory, point to your own local file:

```sh
python3 match_upcs.py /path/to/your-products.csv
```

The command validates the file, selects the first ten distinct valid **input spellings**, prints them and writes `output/customer-upcs/report.json`. It makes **no network requests**, even when an API key is present. To select fewer:

```sh
python3 match_upcs.py /path/to/your-products.csv --column barcode --limit 3
```

The report includes rejected row numbers/reasons, exact duplicates, deferred values and a zero-padded GTIN-14 comparison key. The original 12/13-digit value remains the lookup input. Two equivalent spellings can deliberately occupy two request slots, because exact-first API behavior can return different candidate sets. No field from an unrelated CSV column is used to manufacture a match.

## Opt into current API lookup

After reviewing the dry run, load your existing API key into `COLA_API_KEY` through your normal local environment setup. See [authentication](https://docs.colacloud.us/authentication) for account instructions. This recipe does not create credentials or read `.env` files.

```sh
python3 match_upcs.py /path/to/your-products.csv --lookup
```

Use the same `--column` and `--limit` options as your dry run. Each request can return up to **100 records**, consuming returned-record quota; ten requests can therefore consume up to **1,000 records**. Actual results can be limited by remaining quota. Check [current plans](https://colacloud.us/pricing) and your available usage first. This is not a ten-record operation.

The fixed destination is `https://app.colacloud.us/api/v1/barcode/{input}`. Redirects are refused to keep credentials at that destination. Results are saved after each request. Successful responses print the input, candidate-row count and distinct returned brand strings; multiple strings and missing brands are flagged for review, without inferring product identity. A no-candidate HTTP 404 is recorded and processing continues; other HTTP errors, network failures or malformed responses stop the run with its partial report intact. The API's burst limit can return HTTP 429 even within a ten-request plan; the recipe stops and preserves completed results rather than retrying. There is no automatic retry, detail fetching or pagination. Repeating the command can consume quota again; this is not a resumable job.

The default report is replaced on each run, including dry runs. Use a new local directory to retain separate experiments:

```sh
python3 match_upcs.py /path/to/your-products.csv --lookup --limit 3 --output-dir output/my-evaluation
```

## Read the evaluation brief

Every run, including a dry run, also writes `brief.html` and `brief.md` beside `report.json`, and refreshes them after each request so a stopped run still has a readable summary. Open `brief.html` in a browser or print it to PDF; paste `brief.md` into a ticket or note. To rebuild both from a saved report without any network access:

```sh
python3 evaluation_brief.py output/my-evaluation/report.json
```

The brief reports, from the saved report only:

- **Inputs:** CSV rows read, valid, rejected (with row numbers and reasons), exact duplicates, selected and deferred values.
- **Results:** requests sent, inputs with candidates, with no candidates, failed, and not requested (dry run or after a stop); candidate rows returned, which are approval records rather than distinct products.
- **Per input:** status, candidate-row count, distinct brand strings, flags for multiple or missing brand strings or a capped response, and up to 25 returned candidate rows (TTB ID, brand, product, class, approval date).
- **Next actions** derived from those outcomes, such as how to continue a stopped run without repeating completed requests.
- **Scope and limitations**, dated to the report's creation time, and links to public COLA Cloud references.

Only `brand_name` is inspected for the summary. Other columns are displayed as returned and are not checked for presence or accuracy, and a barcode-only evaluation does not establish catalog completeness. A synthetic stopped run looks like this in Markdown:

```text
- Inputs: 6 CSV rows; 5 valid; 1 rejected; 1 exact duplicates; 4 selected; 0 deferred.
- Results: 3 requests; 1 with candidates; 1 no candidates; 1 failed; 1 not requested.
- Review: 3 candidate rows (approval records, not distinct products); 1 inputs with multiple brand strings; 1 rows without brand.

| CSV record | Input | Status | Candidate rows | Distinct brand strings | Flags |
| 2 | `000000000017` | Candidates returned | 3 | "Synthetic Ridge", "Synthetic Ridge Distilling" | Multiple brand strings; 1 row(s) without a brand string |
| 3 | `000000000024` | No candidates returned (HTTP 404) |  |  |  |
| 4 | `000000000031` | Request failed; run stopped (HTTP 429) |  |  |  |
| 5 | `000000000048` | Not requested (run stopped earlier) |  |  |  |
```

The brief contains the same local input values and account-returned data as `report.json`; share it only as your terms allow. All source text is escaped. The HTML has no scripts or remote assets, and its content security policy blocks them. A Markdown viewer may still turn URL-like text from source data into links.

## Interpret the evidence

The API tries the original string first. If it finds nothing, its bounded recovery can try the equivalent checksum-valid UPC-A / leading-zero EAN-13 spelling. The first nonempty result wins; it does **not** union every equivalent representation. The recipe displays a GTIN-14 comparison key but does not send that padded key or issue additional equivalent-form requests automatically. This endpoint exercise does not reproduce a full normalized-key warehouse benchmark.

A report entry preserves the API's returned `data`, including the candidate list. `returned_record_count` counts returned rows, not proven distinct products. The endpoint's cap and quota mean its response is not proof that you received every possible approval. The current response does not identify which fallback won, so the recipe does not infer it.

For each candidate, compare the brand and expression, age/flavor/finish, proof or ABV, package volume and pack configuration against your own evidence. Where the summary omits a distinguishing field, mark it **unknown**. Multiple approvals can refer to one product; a shared or incorrectly extracted barcode can also return conflicting products. Same-brand or similar-name text is only a plausible candidate, not verified physical-product identity. A missing result does not prove the product lacks an approval or that no other source can identify it. Approval records do not establish current sales or availability.

## Keep customer data local

`output/`, CSVs, `.env` files and caches are Git-ignored here. Keep input lists and returned account data outside public commits; a custom output directory outside `output/` is your responsibility. The code's MIT license does not grant data redistribution rights. Current COLA Cloud terms and your agreement govern account-backed data and its use; see the [data-rights boundary](README.md#data-rights).

This recipe ships no customer lists, licensed benchmark rows, internal export identifiers or dataset downloads. The separate [pinned sample walkthrough](README.md#run-the-barcode-matching-example) remains available for a reproducible, account-free introduction.

## Run the network-free tests

```sh
python3 -m unittest -v test_match_upcs.py test_evaluation_brief.py
```

Fixtures use synthetic identifiers and fake HTTP responses. They verify the dry-run boundary, request cap, string handling, multiple candidates, credential requirement, redirect refusal, partial failure reporting and absence of credentials in saved reports. Brief tests cover dry-run, partial, no-candidate and capped outcomes, wording limits, escaping of hostile strings, and the absence of credentials, scripts and remote assets. They do not make live API calls or establish production endpoint performance.
