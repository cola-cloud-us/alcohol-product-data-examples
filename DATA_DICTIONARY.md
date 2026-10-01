# Data dictionary

`sample.csv` contains exactly 100 rows, one per TTB approval. All CSV fields are strings; empty source values remain empty. Import `ttb_id` and identifiers as text, never numeric spreadsheet columns. Array fields contain JSON strings, parsed with `json.loads`.

| Field | Source and interpretation |
| --- | --- |
| `ttb_id` | `cola.TTB_ID`; identifier of the approval, not a stable distinct-product ID. |
| `brand_name` | `cola.BRAND_NAME`; recorded name, not a canonical brand entity. Trademark rights are not granted. |
| `product_name` | `cola.PRODUCT_NAME`; recorded label/product description. Does not prove current availability. |
| `product_type` | `cola.PRODUCT_TYPE`; broad TTB-derived group (wine, malt beverage, distilled spirits), not the proprietary LLM taxonomy. |
| `permit_number` | `cola.PERMIT_NUMBER`; source permit identifier. Does not establish brand ownership. |
| `approval_date` | `cola.APPROVAL_DATE`; ISO date of the approval in this snapshot. |
| `gtins_json` | Derived sorted unique GTIN-14 strings for accepted UPC-A/EAN-13 evidence. `[]` means no supported valid code in this workflow. |
| `barcode_evidence_json` | Array of `type`, original `value`, normalized `gtin14`, and `ttb_image_id`. Joined from `cola_image_barcode` and validated against `cola_image`. Coordinates, OCR, and images excluded. Evidence can repeat a GTIN across multiple images. |
| `selection_group` | `supported_gtin` or `no_supported_gtin`. This is a workflow classification, not a product attribute. |
| `source_ttb_url` | Constructed public TTB approval-details URL from `ttb_id`. The source may present a session/access challenge. |
| `source_generated_at` | Immutable source manifest timestamp, `2026-08-20T08:47:30Z`; not the time of the current script run. |

Selection is deterministic: SHA-256 order of `cola-aeo-v1:` plus TTB ID within each product-type/evidence stratum. Quotas are wine 24 supported + 16 controls, malt beverage 18 + 12, distilled spirits 18 + 12. The result sorts by TTB ID. It is deliberately stratified for teaching, not random or representative.

The source archive contains classifications from taxonomy 2.0.2 and other enrichment fields. Those classifications and prose enrichments are not included here. The archive's `BARCODE_COLA_OCCURENCES` field is also excluded: the workflow computes candidate membership from the available rows instead of treating that upstream count as a one-to-one identity guarantee.
