#!/usr/bin/env python3
"""Evaluate alcohol product barcode matches against approval evidence using Python's standard library."""

import argparse
import collections
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

SOURCE_URL = "https://dyuie4zgfxmt6.cloudfront.net/samples/cola-sample-pack-v2.zip"
SOURCE_SHA256 = "68e802fd3a67bc443dace3e330d735c67216f3f553730fb1543de69efc964392"
SELECTION = {
    "wine": (24, 16),
    "malt beverage": (18, 12),
    "distilled spirits": (18, 12),
}
FIELDS = [
    "ttb_id", "brand_name", "product_name", "product_type", "permit_number",
    "approval_date", "gtins_json", "barcode_evidence_json", "selection_group",
    "source_ttb_url", "source_generated_at",
]


def normalize_gtin(value):
    """Accept explicit GTIN-12/13/14, not an ambiguous eight-digit UPC-E scan."""
    if not isinstance(value, str) or len(value) not in (12, 13, 14):
        raise ValueError("Provide a GTIN-12, GTIN-13, or GTIN-14 string")
    if not value.isascii() or not value.isdecimal() or set(value) == {"0"}:
        raise ValueError("GTIN must be nonzero ASCII digits; preserve leading zeros")
    total = sum(int(d) * (3 if i % 2 == 0 else 1)
                for i, d in enumerate(reversed(value[:-1])))
    if (10 - total % 10) % 10 != int(value[-1]):
        raise ValueError("Invalid GTIN check digit")
    return value.zfill(14)


def load_source(archive_path):
    archive_path = Path(archive_path)
    if not archive_path.exists():
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "COLA-Cloud-sample-workflow/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Unexpected archive size")
        if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
            raise ValueError("Source archive checksum mismatch")
        archive_path.write_bytes(data)
    data = archive_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("Source archive checksum mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for name, expected in manifest["files"].items():
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != expected["sha256"]:
                raise ValueError(f"Member checksum mismatch: {name}")
            if len(content) != expected["byte_count"]:
                raise ValueError(f"Member byte count mismatch: {name}")
        tables = {}
        for name in ("cola.csv", "cola_image.csv", "cola_image_barcode.csv"):
            tables[name] = list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))
            if len(tables[name]) != manifest["files"][name]["data_row_count"]:
                raise ValueError(f"Member row count mismatch: {name}")
    return tables, manifest


def project(tables, generated_at):
    colas = tables["cola.csv"]
    if len({row["TTB_ID"] for row in colas}) != len(colas):
        raise ValueError("Duplicate source approval IDs")
    ids = {row["TTB_ID"] for row in colas}
    image_ids = {row["TTB_IMAGE_ID"]: row["TTB_ID"] for row in tables["cola_image.csv"]}
    evidence = collections.defaultdict(list)
    decisions = collections.Counter()
    for barcode in tables["cola_image_barcode.csv"]:
        ttb_id = barcode["TTB_ID"]
        if ttb_id not in ids or image_ids.get(barcode["TTB_IMAGE_ID"]) != ttb_id:
            raise ValueError("Barcode evidence has a broken approval/image join")
        kind, value = barcode["BARCODE_TYPE"], barcode["BARCODE_VALUE"]
        if kind not in ("upca", "ean13"):
            decisions["unsupported_symbology"] += 1
            continue
        if len(value) != {"upca": 12, "ean13": 13}[kind]:
            decisions["invalid_length"] += 1
            continue
        try:
            normalized = normalize_gtin(value)
        except ValueError:
            decisions["invalid_check_digit_or_digits"] += 1
            continue
        decisions["accepted_code_rows"] += 1
        evidence[ttb_id].append({"type": kind, "value": value, "gtin14": normalized,
                                  "ttb_image_id": barcode["TTB_IMAGE_ID"]})
    rows = []
    for source in sorted(colas, key=lambda row: row["TTB_ID"]):
        ttb_id = source["TTB_ID"]
        codes = sorted(evidence[ttb_id], key=lambda e: (e["gtin14"], e["ttb_image_id"], e["type"]))
        rows.append({
            "ttb_id": ttb_id, "brand_name": source["BRAND_NAME"],
            "product_name": source["PRODUCT_NAME"], "product_type": source["PRODUCT_TYPE"],
            "permit_number": source["PERMIT_NUMBER"], "approval_date": source["APPROVAL_DATE"],
            "gtins_json": json.dumps(sorted({e["gtin14"] for e in codes}), separators=(",", ":")),
            "barcode_evidence_json": json.dumps(codes, separators=(",", ":")),
            "selection_group": "supported_gtin" if codes else "no_supported_gtin",
            "source_ttb_url": "https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid=" + ttb_id,
            "source_generated_at": generated_at,
        })
    return rows, dict(sorted(decisions.items()))


def select_sample(rows):
    selected = []
    for product_type, quotas in SELECTION.items():
        for group, quota in zip(("supported_gtin", "no_supported_gtin"), quotas):
            candidates = [r for r in rows if r["product_type"] == product_type and r["selection_group"] == group]
            if len(candidates) < quota:
                raise ValueError(f"Not enough source rows for {product_type}/{group}")
            # Hash ordering avoids depending on source ordering or current random state.
            candidates.sort(key=lambda r: hashlib.sha256(("cola-aeo-v1:" + r["ttb_id"]).encode()).hexdigest())
            selected.extend(candidates[:quota])
    return sorted(selected, key=lambda r: r["ttb_id"])


def lookup(rows, gtin):
    normalized = normalize_gtin(gtin)
    return [row for row in rows if normalized in json.loads(row["gtins_json"])]


def build(archive_path, output_dir):
    tables, source_manifest = load_source(archive_path)
    rows, decisions = project(tables, source_manifest["generated_at"])
    sample = select_sample(rows)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "sample.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sample)
    supported = sum(r["selection_group"] == "supported_gtin" for r in rows)
    stats = {
        "scope": "The pinned 1000-approval sample pack only; not a population estimate",
        "source_url": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "source_generated_at": source_manifest["generated_at"],
        "approval_date_min": min(r["approval_date"] for r in rows),
        "approval_date_max": max(r["approval_date"] for r in rows),
        "source_approval_rows": len(rows), "source_code_rows": len(tables["cola_image_barcode.csv"]),
        "approvals_with_any_extracted_code": len({r["TTB_ID"] for r in tables["cola_image_barcode.csv"]}),
        "approvals_with_supported_valid_gtin": supported,
        "approvals_without_supported_valid_gtin": len(rows) - supported,
        "code_row_decisions": decisions,
        "exercise_rows": len(sample),
        "exercise_groups": dict(collections.Counter(r["selection_group"] for r in sample)),
        "exercise_product_types": dict(collections.Counter(r["product_type"] for r in sample)),
        "sample_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "data_terms_url": "https://colacloud.us/terms",
        "rights_status": "Internal evaluation under applicable source/service terms; code license grants no data rights",
        "source_field_presence": {
            field: {"nonempty_rows": sum(bool(r[field].strip()) for r in rows),
                    "total_rows": len(rows)}
            for field in ("brand_name", "product_name", "permit_number", "approval_date")
        },
    }
    (output_dir / "report.json").write_text(json.dumps(stats, indent=2) + "\n")
    return sample, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(".cache/cola-sample-pack-v2.zip"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--gtin", help="Optional GTIN-12/13/14 lookup within the 100-row exercise")
    args = parser.parse_args()
    rows, stats = build(args.archive, args.output)
    print(json.dumps({"report": stats, **({"candidates": lookup(rows, args.gtin)} if args.gtin else {})}, indent=2))


if __name__ == "__main__":
    main()
