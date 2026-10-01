# Alcohol product data examples

Evaluate barcode matches for a beer, wine or spirits catalog with **runnable Python, a notebook and traceable source evidence**. This first example uses a pinned COLA Cloud sample to find candidate alcohol label approvals for a UPC/EAN. It keeps ambiguous matches and missing data visible so you can assess whether the data fits your workflow.

You get code and documentation here. The source data stays at its [canonical sample archive](https://dyuie4zgfxmt6.cloudfront.net/samples/cola-sample-pack-v2.zip); the script downloads it locally for internal evaluation. No dataset, generated CSV, images or notebook outputs are distributed in this repository. See [data rights](#data-rights) before using the results elsewhere.

## Run the barcode-matching example

Python 3.10 or newer, using only the standard library. No API key, database, paid account or model call is required.

```sh
python3 workflow.py --archive .cache/cola-sample-pack-v2.zip --output output
python3 -m unittest -v test_workflow.py
```

The first command downloads the pinned 474 KB archive once, verifies its SHA-256 and manifest file checksums, byte counts and CSV row counts, then writes:

- `output/sample.csv`: 100 approval records with supported GTIN candidates and source evidence.
- `output/report.json`: source identity, selection, field-presence counts and barcode eligibility decisions.

Reruns reuse and revalidate the archive. Cache and output directories are Git-ignored. Keep them local; their data rights are separate from the code license.

Open [barcode-to-cola.ipynb](barcode-to-cola.ipynb) for the same walkthrough in a Python notebook. It selects a real GTIN from the downloaded sample and displays candidate approval IDs, image-record evidence and a public source link. Jupyter is optional. To reuse an existing local archive/output location, set `COLA_SAMPLE_ARCHIVE` and `COLA_SAMPLE_OUTPUT` for the notebook, or use the script flags shown above.

For your own known code, use `--gtin` with a quoted GTIN-12, GTIN-13 or GTIN-14 string. The lookup only searches the 100-row exercise; a miss says nothing about the full dataset.

## What the example contains

| Data | What you can evaluate |
| --- | --- |
| Recorded brand and product names | Import source strings; blanks remain blank. These are not canonical brand or product identities. |
| Product type, permit and approval date | Source context for wine, malt beverages and distilled spirits. A permit does not establish brand ownership. |
| Extracted UPC-A / EAN-13 | Original value, code type, normalized GTIN-14 and related image-record ID. |
| Source evidence | Approval identifier, snapshot date and public TTB details URL for inspecting candidates. |
| ABV, bottle size and images | Not included in this example's output. This example isolates identifier matching; evaluate those fields and image rights separately for your app. |

The [data dictionary](DATA_DICTIONARY.md) defines every output field and its unit. The source archive contains additional enrichment fields; this local projection does not copy label images, OCR text, image storage keys, tasting notes or proprietary classifications.

## How matching works

Identifiers stay strings to preserve leading zeros. Only source rows explicitly labeled `upca` with 12 digits or `ean13` with 13 digits enter the index, and their check digit must pass. Accepted values are zero-padded to GTIN-14. QR, Codabar and compressed UPC-E are excluded. The code does not strip arbitrary punctuation or repair invalid identifiers.

The check digit follows [GS1's calculation](https://www.gs1.org/services/how-calculate-check-digit-manually); [GS1's data-exchange guide](https://www.gs1.org/edi-xml/technical-user-guide/Item_Numbers) explains zero-padding. Valid syntax does not prove GS1 assignment, correct extraction or product identity.

The workflow verifies barcode → image → approval joins, retains all accepted evidence and returns every matching approval. Multiple approvals can describe the same product, and reused or misread codes require review. An approval does not prove current retail availability or sales. Label artwork is different from bottle photography.

## Reproduce the sample's field coverage

The pinned source was generated **August 20, 2026**, with approval dates August 13–17. In its 1,000 approval records, **469 have at least one extracted code; 433 have a checksum-valid supported UPC-A or EAN-13 under this workflow**. There are 437 accepted numeric code rows and 89 excluded code rows. The report reproduces the decisions and counts nonempty name, permit and date fields.

This measures workflow eligibility in that source snapshot. It is not national product coverage, extraction recall, match precision, or verified barcode ownership. The 100-row teaching subset deliberately selects 60 approvals with supported codes and 40 without: wine 40, malt beverages 30, distilled spirits 30. Its designed 60% split is not measured coverage. Missing supported evidence does not mean the physical product lacks a barcode.

The original sample archive remains the single maintained data source. Its SHA-256 is pinned in the script; an unexpected replacement fails verification instead of silently changing the exercise.

## Apply the workflow to your use case

Use your own known products to evaluate candidate multiplicity, exact package size, ABV, missing fields and image suitability before choosing a source. Keep human-reviewed product matches separate from identifier-only candidates. Confirm the license for your intended display, storage and delivery method.

[COLA Cloud](https://colacloud.us/product-enrichment) provides enriched approval records through its web app, REST API, SDKs, CLI, read-only assistant connection and licensed bulk delivery. See [developer docs](https://docs.colacloud.us), [current plans](https://colacloud.us/pricing) and [bulk delivery](https://colacloud.us/bulk-data) for current access and terms. Self-service history starts in 2005; this dated sample covers a much narrower period.

For whiskey-specific evaluation, the [whiskey dataset page](https://colacloud.us/data-packs/whiskey) and [import and matching guide](https://colacloud.us/blog/whiskey-dataset-evaluation) describe a separate, small whiskey sample and by-request offering. This repository's barcode exercise uses the cross-category source archive above, not that whiskey sample.

An optional current-data follow-up is to connect the [read-only assistant tools](https://colacloud.us/mcp) using the documented OAuth or developer-client API-key flow. Ask it to search an actual GTIN from your exercise, inspect candidate approvals and explain uncertainty. `search_colas` and `get_cola` are the relevant tools; consult their current schemas for supported arguments. The script and notebook make no account-backed calls and spend no account quota. Never paste an API key into a chat or notebook you will share.

## Data rights

[MIT](LICENSE) licenses this repository's software and documentation, copyright COLA Cloud LLC. It does **not** license downloaded data, generated data outputs, label artwork, trademarks, service access or API credentials.

Use the sample for internal evaluation under the [current COLA Cloud Terms of Service](https://colacloud.us/terms), any applicable sample/plan terms and your signed agreement. This example does not grant permission to redistribute the archive or generated CSV, publish a commercial catalog, or use the data for model training. Sections 6 and 14 distinguish examples and open-source code from data rights. Contact [help@colacloud.us](mailto:help@colacloud.us) for a license covering other uses. Public-source records independently obtained outside COLA Cloud retain their independent legal status.
