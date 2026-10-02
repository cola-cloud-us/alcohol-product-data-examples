#!/usr/bin/env python3
"""Bounded, opt-in current-API evaluation of a customer's own UPC/EAN CSV."""

import argparse
import csv
import datetime
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from workflow import normalize_gtin

ENDPOINT = "https://app.colacloud.us/api/v1/barcode/"
MAX_LOOKUPS = 10
MAX_RESPONSE_BYTES = 5_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the customer's API key through a redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


def plan_csv(path, column="upc", limit=MAX_LOOKUPS):
    if not 1 <= limit <= MAX_LOOKUPS:
        raise ValueError("limit must be between 1 and 10")
    selected, rejected, seen = [], [], set()
    duplicates = valid = total = 0
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or reader.fieldnames.count(column) != 1:
            raise ValueError("CSV must contain the requested column exactly once")
        for line, row in enumerate(reader, 2):
            total += 1
            value = row.get(column)
            try:
                if value is None or len(value) not in (12, 13):
                    raise ValueError("Expected a 12-digit UPC-A or 13-digit EAN-13 string")
                gtin14 = normalize_gtin(value)
            except ValueError as exc:
                rejected.append({"csv_record": line, "value": value, "reason": str(exc)})
                continue
            valid += 1
            if value in seen:
                duplicates += 1
                continue
            seen.add(value)
            if len(selected) < limit:
                selected.append({"csv_record": line, "input_upc": value, "gtin14": gtin14})
    return {
        "input_rows": total, "valid_rows": valid, "duplicate_exact_strings": duplicates,
        "unique_valid_strings": len(seen), "deferred_unique_strings": len(seen) - len(selected),
        "selected": selected, "rejected": rejected,
    }


def lookup(value, api_key, opener):
    request = urllib.request.Request(
        ENDPOINT + value,
        headers={"Authorization": "Bearer " + api_key,
                 "Accept": "application/json", "User-Agent": "COLA-Cloud-UPC-example/1.0"},
    )
    try:
        with opener.open(request, timeout=30) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
        if len(content) > MAX_RESPONSE_BYTES:
            return {"status": "invalid_response", "stop": True}
        payload = json.loads(content)
        data = payload.get("data") if isinstance(payload, dict) else None
        candidates = data.get("colas") if isinstance(data, dict) else None
        if not isinstance(candidates, list) or not all(isinstance(c, dict) for c in candidates):
            return {"status": "invalid_response", "stop": True}
        return {"status": "candidates_returned", "stop": False,
                "returned_record_count": len(candidates), "api_data": data}
    except urllib.error.HTTPError as exc:
        # Never persist an error body or exception string: either may contain sensitive data.
        status = exc.code
        exc.close()
        return {"status": "no_candidates" if status == 404 else "http_error",
                "http_status": status, "stop": status != 404}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "network_error", "stop": True}
    except (ValueError, UnicodeError):
        return {"status": "invalid_response", "stop": True}


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def main(argv=None, *, opener=None, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("--column", default="upc")
    parser.add_argument("--limit", type=int, choices=range(1, 11), default=10,
                        help="Select at most this many distinct input spellings (1–10)")
    parser.add_argument("--output-dir", type=Path, default=Path("output/customer-upcs"))
    parser.add_argument("--lookup", action="store_true",
                        help="Send selected values to the current API; consumes account record quota")
    args = parser.parse_args(argv)
    try:
        plan = plan_csv(args.input_csv, args.column, args.limit)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    env = os.environ if environ is None else environ
    api_key = env.get("COLA_API_KEY") if args.lookup else None
    if args.lookup and (not api_key or "\n" in api_key or "\r" in api_key):
        parser.error("--lookup requires an existing COLA_API_KEY environment variable")
    report = {
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "lookup" if args.lookup else "dry_run", "plan": plan,
        "request_count": 0, "results": [],
        "limits": {"maximum_requests": len(plan["selected"]),
                   "maximum_records_per_request": 100,
                   "maximum_record_quota_for_plan": 100 * len(plan["selected"])},
        "interpretation": "Candidate approvals, not verified product/package identities. "
                          "API exact-first with bounded 12/13-digit fallback, not a normalized warehouse union.",
    }
    destination = args.output_dir / "report.json"
    save_report(destination, report)
    print(f"Selected {len(plan['selected'])} of {plan['unique_valid_strings']} unique valid strings.")
    for item in plan["selected"]:
        print(f"  {item['input_upc']} -> comparison GTIN-14 {item['gtin14']}")
    print(f"Rejected {len(plan['rejected'])} rows; report: {destination}")
    if not args.lookup:
        print("Dry run: no network requests. Add --lookup only when ready to use account quota.")
        return 0
    print(f"Lookup plan: at most {len(plan['selected'])} requests and "
          f"{report['limits']['maximum_record_quota_for_plan']} returned-record quota.")
    client = opener if opener is not None else urllib.request.build_opener(NoRedirect())
    for item in plan["selected"]:
        result = lookup(item["input_upc"], api_key, client)
        report["request_count"] += 1
        report["results"].append({**item, **result})
        save_report(destination, report)
        if result["stop"]:
            print(f"Stopped after {report['request_count']} request(s): {result['status']}. "
                  "Partial report saved; no automatic retry.")
            return 1
    print(f"Finished {report['request_count']} request(s). Review candidates and ambiguity in the report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
