"""Network-free brief tests: all identifiers and responses below are synthetic."""
import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
import urllib.error

import evaluation_brief as brief
import match_upcs as recipe
from test_match_upcs import FakeHTTP, barcode


def colas(*brands, **extra):
    return json.dumps({'data': {'colas': [{'ttb_id': f'SYN{i}', 'brand_name': b, **extra}
                                          for i, b in enumerate(brands)]}}).encode()


class EvaluationBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'own.csv'
        self.out = self.root / 'output'

    def run_recipe(self, values, *flags, responses=(), key='fake-secret-key'):
        self.csv.write_text('upc\n' + '\n'.join(values) + '\n')
        client = FakeHTTP(responses)
        with contextlib.redirect_stdout(io.StringIO()):
            status = recipe.main([str(self.csv), '--output-dir', str(self.out), *flags],
                                 opener=client, environ={'COLA_API_KEY': key})
        self.html = (self.out / 'brief.html').read_text()
        self.md = (self.out / 'brief.md').read_text()
        return status, json.loads((self.out / 'report.json').read_text())

    def test_dry_run_brief_reports_scope_without_requests_or_results(self):
        values = [barcode(i) for i in range(1, 13)] + ['12345', barcode(1)]
        status, report = self.run_recipe(values)
        self.assertEqual(status, 0)
        rows = brief.build_rows(report)
        self.assertEqual([r['label'] for r in rows], ['Not requested (dry run)'] * 10)
        summary = brief.summarize(report, rows)
        self.assertEqual((summary['input_rows'], summary['rejected_rows'], summary['duplicates'],
                          summary['selected'], summary['deferred'], summary['requests']), (14, 1, 1, 10, 2, 0))
        self.assertIn('Dry run (no requests sent)', self.html)
        self.assertIn('rerun with --lookup', self.html)
        self.assertIn('up to 1,000 returned-record quota', self.html)
        self.assertIn('2 distinct valid value(s) were deferred', self.md)
        self.assertNotIn('Candidates returned', self.html)

    def test_partial_run_separates_candidates_no_match_failure_and_unrequested(self):
        values = [barcode(i) for i in range(1, 5)]
        responses = [colas('Synthetic A', 'Synthetic B', None),
                     urllib.error.HTTPError('fixture', 404, 'body', {}, None),
                     urllib.error.HTTPError('fixture', 429, 'sensitive body', {}, None)]
        status, report = self.run_recipe(values, '--lookup', responses=responses)
        self.assertEqual(status, 1)
        rows = brief.build_rows(report)
        self.assertEqual([r['status'] for r in rows],
                         ['candidates_returned', 'no_candidates', 'http_error', 'not_requested'])
        self.assertEqual(rows[3]['label'], 'Not requested (run stopped earlier)')
        self.assertEqual(rows[0]['flags'], ['Multiple brand strings', '1 row(s) without a brand string'])
        summary = brief.summarize(report, rows)
        self.assertEqual((summary['with_candidates'], summary['no_candidates'], summary['failed'],
                          summary['not_requested'], summary['candidate_rows']), (1, 1, 1, 1, 3))
        self.assertIn('Request failed; run stopped (HTTP 429)', self.html)
        self.assertIn('does not prove the product lacks an approval', self.html)
        self.assertIn('put only the not-requested values in a new CSV', self.html)
        self.assertNotIn('sensitive body', self.html + self.md)

    def test_all_no_candidates_never_claims_absence(self):
        errors = [urllib.error.HTTPError('fixture', 404, 'body', {}, None) for _ in range(2)]
        status, _ = self.run_recipe([barcode(1), barcode(2)], '--lookup', responses=errors)
        self.assertEqual(status, 0)
        self.assertEqual(self.html.count('No candidates returned (HTTP 404)'), 2)
        self.assertIn('not proof that no approval', self.html)
        self.assertNotIn('rerun with --lookup', self.html)

    def test_wording_limits_inspection_and_identity_claims(self):
        self.run_recipe([barcode(1)], '--lookup', responses=[colas('Synthetic', product_name=None)])
        for text in (self.html, self.md):
            self.assertIn('not verified products', text)
            self.assertRegex(text, r'Only brand\\?_name was inspected')
            self.assertIn('does not establish catalog completeness', text)
            self.assertNotRegex(text.lower(), r'(?<!not )verified (match|product)|\bcomplete (coverage|catalog)|\bconfirmed\b')

    def test_response_cap_flagged(self):
        self.run_recipe([barcode(1)], '--lookup', responses=[colas(*['Synthetic'] * 100)])
        self.assertIn('Response cap reached; more approvals may exist', self.html)
        self.assertIn('75 more row(s) in report.json', self.html)

    def test_hostile_strings_are_escaped_in_html_and_markdown(self):
        hostile = '<script>alert(1)</script><img src=https://evil.example/x> [x](https://evil.example) |\n# h'
        self.run_recipe([barcode(1)], '--lookup',
                        responses=[colas(hostile, product_name='"><iframe src=//evil.example>')])
        self.assertNotIn('<script>alert', self.html)
        self.assertNotIn('<img', self.html)
        self.assertNotIn('<iframe', self.html)
        self.assertIn('&lt;script&gt;', self.html)
        self.assertNotRegex(self.md, r'(?<!\\)<(script|img)')
        self.assertNotRegex(self.md, r'(?<!\\)\]\(https://evil')
        self.assertNotIn('\n# h', self.md)
        self.assertEqual(len(re.findall(r'^\| \d+ \|', self.md, re.M)), 1)

    def test_rejected_values_and_control_characters_are_neutralized(self):
        self.csv.write_text('upc\n"<b>1\x1b[31m"\n')
        with contextlib.redirect_stdout(io.StringIO()):
            recipe.main([str(self.csv), '--output-dir', str(self.out)], opener=FakeHTTP([]), environ={})
        html_text = (self.out / 'brief.html').read_text()
        self.assertIn('&lt;b&gt;1�[31m', html_text)
        self.assertNotIn('\x1b', html_text + (self.out / 'brief.md').read_text())

    def test_no_key_scripts_or_remote_assets(self):
        self.run_recipe([barcode(1)], '--lookup', responses=[colas('Synthetic')], key='fake-secret-key')
        for text in (self.html, self.md):
            self.assertNotIn('fake-secret-key', text)
        self.assertNotIn('<script', self.html.lower())
        self.assertIn("default-src 'none'", self.html)
        self.assertNotRegex(self.html, r'(src|@import|url\()\s*[=(]?\s*["\']?https?:')
        hrefs = re.findall(r'href="([^"]+)"', self.html)
        self.assertEqual(hrefs, [url for _, url in brief.TRUST_LINKS])
        self.assertIn('@media print', self.html)

    def test_standalone_render_from_saved_report_is_offline_and_identical(self):
        self.run_recipe([barcode(1)], '--lookup', responses=[colas('Synthetic')])
        original = self.html
        (self.out / 'brief.html').unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(brief.main([str(self.out / 'report.json')]), 0)
        self.assertEqual((self.out / 'brief.html').read_text(), original)


if __name__ == '__main__':
    unittest.main()
