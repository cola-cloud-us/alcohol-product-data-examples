#!/usr/bin/env python3
"""Render a local, human-readable evaluation brief from a match_upcs.py report.json.

Rendering is offline: it reads only the saved report and writes brief.html and
brief.md beside it. It makes no network requests and embeds no remote assets.
"""

import argparse
import html
import json
from pathlib import Path
import re

TRUST_LINKS = [
    ("Data provenance and dated coverage", "https://docs.colacloud.us/trust/data-provenance"),
    ("API authentication", "https://docs.colacloud.us/authentication"),
    ("Plans and record quota", "https://colacloud.us/pricing"),
    ("No-key quickstart", "https://docs.colacloud.us/quickstart"),
]
INSPECTED_FIELDS = ("brand_name",)
CANDIDATE_COLUMNS = (("ttb_id", "TTB ID"), ("brand_name", "Brand"), ("product_name", "Product"),
                     ("class_name", "Class"), ("approval_date", "Approved"))
MAX_CANDIDATE_ROWS = 25
STATUS_LABELS = {
    "candidates_returned": "Candidates returned",
    "no_candidates": "No candidates returned",
    "http_error": "Request failed; run stopped",
    "network_error": "Network failure; run stopped",
    "invalid_response": "Unreadable response; run stopped",
}
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f  ]")
MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>|~&])")


def clean(value):
    """Source text as one display line: no control characters, no layout injection."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value)
    return CONTROL.sub("�", text.replace("\r\n", " ").replace("\n", " ").replace("\t", " "))


def brand_summary(candidates):
    brands = sorted({c["brand_name"] for c in candidates
                     if isinstance(c.get("brand_name"), str) and c["brand_name"].strip()})
    missing = sum(not isinstance(c.get("brand_name"), str) or not c["brand_name"].strip()
                  for c in candidates)
    return brands, missing


def build_rows(report):
    """One row per selected input, including values never requested."""
    results = {r["csv_record"]: r for r in report.get("results", [])}
    stopped = any(r.get("stop") for r in results.values())
    rows = []
    for item in report["plan"]["selected"]:
        result = results.get(item["csv_record"])
        row = {"csv_record": item["csv_record"], "input_upc": item["input_upc"],
               "gtin14": item["gtin14"], "candidates": [], "brands": [], "missing_brand": 0,
               "flags": []}
        if result is None:
            row["status"] = "not_requested"
            row["label"] = ("Not requested (dry run)" if report["mode"] == "dry_run"
                            else "Not requested (run stopped earlier)" if stopped
                            else "Not requested (run incomplete)")
        else:
            row["status"] = result["status"]
            row["label"] = STATUS_LABELS.get(result["status"], clean(result["status"]))
            if "http_status" in result:
                row["label"] += f" (HTTP {int(result['http_status'])})"
            if result["status"] == "candidates_returned":
                row["candidates"] = result["api_data"]["colas"]
                row["brands"], row["missing_brand"] = brand_summary(row["candidates"])
                if len(row["brands"]) > 1:
                    row["flags"].append("Multiple brand strings")
                if row["missing_brand"]:
                    row["flags"].append(f"{row['missing_brand']} row(s) without a brand string")
                if len(row["candidates"]) >= report["limits"]["maximum_records_per_request"]:
                    row["flags"].append("Response cap reached; more approvals may exist")
        rows.append(row)
    return rows


def summarize(report, rows):
    plan = report["plan"]
    counts = {s: sum(r["status"] == s for r in rows)
              for s in ("candidates_returned", "no_candidates", "not_requested")}
    return {
        "input_rows": plan["input_rows"], "valid_rows": plan["valid_rows"],
        "rejected_rows": len(plan["rejected"]), "duplicates": plan["duplicate_exact_strings"],
        "unique_valid": plan["unique_valid_strings"], "selected": len(plan["selected"]),
        "deferred": plan["deferred_unique_strings"], "requests": report["request_count"],
        "with_candidates": counts["candidates_returned"], "no_candidates": counts["no_candidates"],
        "failed": len(rows) - sum(counts.values()), "not_requested": counts["not_requested"],
        "candidate_rows": sum(len(r["candidates"]) for r in rows),
        "multiple_brands": sum(len(r["brands"]) > 1 for r in rows),
        "missing_brand_rows": sum(r["missing_brand"] for r in rows),
    }


def next_actions(report, rows, s):
    actions = []
    if report["mode"] == "dry_run":
        actions.append(f"Review the selected values, then rerun with --lookup to send them. That run makes at most "
                       f"{s['selected']} request(s) and can consume up to {report['limits']['maximum_record_quota_for_plan']:,} "
                       "returned-record quota. Use a new --output-dir to keep this dry run.")
    if s["with_candidates"]:
        actions.append("For each input with candidates, compare brand and expression, age/flavor/finish, proof or ABV, "
                       "volume and pack configuration against your own product evidence. Mark any field you could not "
                       "check as unknown.")
    if s["multiple_brands"] or s["missing_brand_rows"]:
        actions.append("Review flagged inputs first: differing or missing brand strings can be naming variants, "
                       "shared or mis-extracted barcodes, or distinct products. This brief does not decide which.")
    if s["no_candidates"]:
        actions.append("For inputs with no candidates, confirm the value in your own system and consider searching by "
                       "brand in the app. No candidates does not prove the product lacks an approval.")
    if s["failed"] or (report["mode"] == "lookup" and s["not_requested"]):
        actions.append("The run stopped before every selected value was requested. Rerunning the same CSV repeats "
                       "completed requests and their quota use; to continue, put only the not-requested values in a "
                       "new CSV and use a new --output-dir. Wait before retrying a rate limit (HTTP 429).")
    if s["rejected_rows"]:
        actions.append("Fix rejected rows at the source export: keep barcodes as text with leading zeros. The recipe "
                       "does not repair values.")
    if s["deferred"]:
        actions.append(f"{s['deferred']} distinct valid value(s) were deferred by the ten-request bound. Evaluate them "
                       "in further small runs, or see plans for larger account-backed use.")
    return actions


def limitations(report):
    return [
        f"Dated run: generated from a report created {report['created_at_utc']}. Results reflect the API and account "
        "quota at that time and are not a monitored or refreshed view.",
        "Candidates are label approvals (COLAs) returned for a barcode, not verified products or packages. "
        "Several approvals can describe one product; one barcode can return unrelated products.",
        "Only brand_name was inspected for this summary. Other displayed fields are shown as returned and were not "
        "checked for presence, completeness or accuracy.",
        "Barcode-only evidence does not establish catalog completeness or current sales and availability.",
        "The API tries the exact input first, then a bounded 12/13-digit equivalent; it does not union every "
        "equivalent form, and each request returns at most "
        f"{report['limits']['maximum_records_per_request']} records.",
        "An input with no candidates is not proof that no approval or other source identifies the product.",
    ]


CSS = """
:root { color-scheme: light; --ink:#1c1917; --muted:#57534e; --line:#d6d3d1; --soft:#f5f5f4; --warn:#92400e; }
* { box-sizing: border-box; }
body { margin: 0 auto; max-width: 960px; padding: 32px 24px 64px; color: var(--ink);
       font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
h1 { font-size: 24px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 32px 0 8px; border-bottom: 1px solid var(--line); padding-bottom: 4px; }
h3 { font-size: 15px; margin: 20px 0 6px; } p, li { color: var(--ink); } .muted { color: var(--muted); }
.note { background: var(--soft); border-left: 3px solid var(--line); padding: 8px 12px; margin: 12px 0; }
dl.stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; margin: 8px 0; }
dl.stats div { border: 1px solid var(--line); border-radius: 6px; padding: 8px 10px; }
dt { font-size: 12px; color: var(--muted); } dd { margin: 0; font-size: 20px; font-variant-numeric: tabular-nums; }
table { width: 100%; border-collapse: collapse; margin: 6px 0 12px; font-size: 13px; }
th, td { text-align: left; vertical-align: top; padding: 5px 8px; border-bottom: 1px solid var(--line); overflow-wrap: anywhere; }
th { background: var(--soft); font-weight: 600; } code { font: 12px ui-monospace, Menlo, Consolas, monospace; }
.flag { color: var(--warn); font-weight: 600; } .input { break-inside: avoid; }
a { color: inherit; }
@media print {
  body { max-width: none; padding: 0; font-size: 11pt; }
  h2 { break-after: avoid; } table, .input, dl.stats div { break-inside: avoid; }
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 9pt; color: var(--muted); }
  .note { border-left-color: #888; }
}
"""


def render_html(report):
    e = lambda value: html.escape(clean(value), quote=True)
    rows = build_rows(report)
    s = summarize(report, rows)
    mode = "Dry run (no requests sent)" if report["mode"] == "dry_run" else "Current API lookup"
    stat = lambda label, value: f"<div><dt>{e(label)}</dt><dd>{int(value):,}</dd></div>"
    out = [
        "<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
        # Defense in depth: even a rendering mistake cannot load scripts, images or remote styles.
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">",
        '<meta name="referrer" content="no-referrer">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>UPC evaluation brief</title>", f"<style>{CSS}</style></head><body>",
        "<h1>UPC evaluation brief</h1>",
        f"<p class=\"muted\">{e(mode)} · report created {e(report['created_at_utc'])}</p>",
        "<p class=\"note\">Contains your local input values and any account-returned data. Share it only as your "
        "COLA Cloud terms and agreement allow. Candidates below are approvals to review, not verified products.</p>",
        "<h2>Inputs</h2><dl class=\"stats\">",
        stat("CSV rows read", s["input_rows"]), stat("Valid rows", s["valid_rows"]),
        stat("Rejected rows", s["rejected_rows"]), stat("Exact duplicates", s["duplicates"]),
        stat("Selected values", s["selected"]), stat("Deferred values", s["deferred"]),
        "</dl><h2>Results</h2><dl class=\"stats\">",
        stat("Requests sent", s["requests"]), stat("With candidates", s["with_candidates"]),
        stat("No candidates", s["no_candidates"]), stat("Failed", s["failed"]),
        stat("Not requested", s["not_requested"]), stat("Candidate rows returned", s["candidate_rows"]),
        stat("Inputs with multiple brands", s["multiple_brands"]),
        stat("Rows without brand", s["missing_brand_rows"]),
        "</dl><p class=\"muted\">Candidate rows are returned approval records, not distinct products.</p>",
        "<h2>Next actions</h2><ol>", *[f"<li>{e(a)}</li>" for a in next_actions(report, rows, s)], "</ol>",
        "<h2>Per input</h2>",
    ]
    for row in rows:
        out.append(f"<section class=\"input\"><h3><code>{e(row['input_upc'])}</code> · {e(row['label'])}</h3>")
        out.append(f"<p class=\"muted\">CSV record {int(row['csv_record'])} · comparison GTIN-14 "
                   f"<code>{e(row['gtin14'])}</code></p>")
        if row["status"] == "candidates_returned":
            out.append(f"<p>{len(row['candidates']):,} candidate row(s); distinct brand strings: "
                       f"{e(', '.join(json.dumps(b, ensure_ascii=False) for b in row['brands']) or 'none')}</p>")
            for flag in row["flags"]:
                out.append(f"<p class=\"flag\">{e(flag)} — review needed</p>")
            if row["candidates"]:
                out.append("<table><thead><tr>" + "".join(f"<th>{e(h)}</th>" for _, h in CANDIDATE_COLUMNS)
                           + "</tr></thead><tbody>")
                for c in row["candidates"][:MAX_CANDIDATE_ROWS]:
                    out.append("<tr>" + "".join(f"<td>{e(c.get(k))}</td>" for k, _ in CANDIDATE_COLUMNS) + "</tr>")
                out.append("</tbody></table>")
                if len(row["candidates"]) > MAX_CANDIDATE_ROWS:
                    out.append(f"<p class=\"muted\">{len(row['candidates']) - MAX_CANDIDATE_ROWS:,} more row(s) "
                               "in report.json.</p>")
        out.append("</section>")
    if report["plan"]["rejected"]:
        out.append("<h2>Rejected rows</h2><table><thead><tr><th>CSV record</th><th>Value</th><th>Reason</th></tr>"
                   "</thead><tbody>")
        for r in report["plan"]["rejected"]:
            value = "(missing)" if r["value"] is None else clean(r["value"])[:40]
            out.append(f"<tr><td>{int(r['csv_record'])}</td><td><code>{e(value)}</code></td><td>{e(r['reason'])}</td></tr>")
        out.append("</tbody></table>")
    out += ["<h2>Scope and limitations</h2><ul>", *[f"<li>{e(t)}</li>" for t in limitations(report)],
            f"<li>Fields inspected: {e(', '.join(INSPECTED_FIELDS))}.</li></ul>",
            "<h2>Public references</h2><ul>",
            *[f"<li><a href=\"{e(url)}\" rel=\"noreferrer\">{e(label)}</a></li>" for label, url in TRUST_LINKS],
            "</ul></body></html>"]
    return "\n".join(out) + "\n"


def md(value):
    return MARKDOWN_SPECIAL.sub(r"\\\1", clean(value))


def render_markdown(report):
    rows = build_rows(report)
    s = summarize(report, rows)
    mode = "Dry run (no requests sent)" if report["mode"] == "dry_run" else "Current API lookup"
    out = [
        "# UPC evaluation brief", "", f"{mode} · report created {md(report['created_at_utc'])}", "",
        "> Contains your local input values and any account-returned data. Share it only as your COLA Cloud terms "
        "and agreement allow. Candidates are approvals to review, not verified products.", "",
        "## Summary", "",
        f"- Inputs: {s['input_rows']:,} CSV rows; {s['valid_rows']:,} valid; {s['rejected_rows']:,} rejected; "
        f"{s['duplicates']:,} exact duplicates; {s['selected']:,} selected; {s['deferred']:,} deferred.",
        f"- Results: {s['requests']:,} requests; {s['with_candidates']:,} with candidates; "
        f"{s['no_candidates']:,} no candidates; {s['failed']:,} failed; {s['not_requested']:,} not requested.",
        f"- Review: {s['candidate_rows']:,} candidate rows (approval records, not distinct products); "
        f"{s['multiple_brands']:,} inputs with multiple brand strings; {s['missing_brand_rows']:,} rows without brand.",
        "", "## Next actions", "", *[f"{i}. {md(a)}" for i, a in enumerate(next_actions(report, rows, s), 1)],
        "", "## Per input", "", "| CSV record | Input | Status | Candidate rows | Distinct brand strings | Flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        brands = ", ".join(json.dumps(b, ensure_ascii=False) for b in row["brands"])
        count = len(row["candidates"]) if row["status"] == "candidates_returned" else ""
        out.append(f"| {int(row['csv_record'])} | `{clean(row['input_upc']).replace('`', '')}` | {md(row['label'])} | "
                   f"{count} | {md(brands)} | {md('; '.join(row['flags']))} |")
    if report["plan"]["rejected"]:
        out += ["", "## Rejected rows", "", "| CSV record | Value | Reason |", "| --- | --- | --- |"]
        for r in report["plan"]["rejected"]:
            value = "(missing)" if r["value"] is None else clean(r["value"])[:40]
            out.append(f"| {int(r['csv_record'])} | {md(value)} | {md(r['reason'])} |")
    out += ["", "Candidate details are in brief.html and report.json.", "", "## Scope and limitations", "",
            *[f"- {md(t)}" for t in limitations(report)], f"- Fields inspected: {', '.join(INSPECTED_FIELDS)}.",
            "", "## Public references", "", *[f"- [{label}]({url})" for label, url in TRUST_LINKS]]
    return "\n".join(out) + "\n"


def write_brief(report, output_dir):
    output_dir = Path(output_dir)
    for name, text in (("brief.html", render_html(report)), ("brief.md", render_markdown(report))):
        temporary = output_dir / (name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(output_dir / name)
    return output_dir / "brief.html"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, nargs="?", default=Path("output/customer-upcs/report.json"))
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        path = write_brief(report, args.report.parent)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"could not render a brief from {args.report}: {exc}")
    print(f"Brief: {path} (and brief.md). Rendered locally; no network requests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
