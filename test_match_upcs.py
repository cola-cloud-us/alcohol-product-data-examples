"""Network-free fixtures: all identifiers and responses below are synthetic."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request

import match_upcs as recipe


class FakeResponse(io.BytesIO):
    pass


class FakeHTTP:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


def barcode(number):
    body = str(number).zfill(11)
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str((-total) % 10)


class CustomerRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.csv = self.root / 'own.csv'
        self.out = self.root / 'output'

    def run_recipe(self, values, *flags, responses=(), env=None):
        self.csv.write_text('upc\n' + '\n'.join(values) + '\n')
        client = FakeHTTP(responses)
        with contextlib.redirect_stdout(io.StringIO()):
            status = recipe.main([str(self.csv), '--output-dir', str(self.out), *flags],
                                 opener=client, environ={} if env is None else env)
        return status, client, json.loads((self.out / 'report.json').read_text())

    def test_dry_run_even_with_key_and_ten_request_bound(self):
        status, client, report = self.run_recipe([barcode(i) for i in range(1, 13)], env={'COLA_API_KEY': 'fake'})
        self.assertEqual(status, 0)
        self.assertEqual(client.requests, [])
        self.assertEqual(len(report['plan']['selected']), 10)
        self.assertEqual(report['plan']['deferred_unique_strings'], 2)

    def test_strict_validation_and_exact_spelling_dedup(self):
        value = barcode(1)
        _, _, report = self.run_recipe([value, value, '0' + value, '000000000000',
                                        value[:-1] + str((int(value[-1]) + 1) % 10),
                                        ' ' + value, '٠' * 12, '00' + value])
        self.assertEqual([r['input_upc'] for r in report['plan']['selected']], [value, '0' + value])
        self.assertEqual(report['plan']['duplicate_exact_strings'], 1)
        self.assertEqual(len(report['plan']['rejected']), 5)
        self.assertEqual(len({r['gtin14'] for r in report['plan']['selected']}), 1)

    def test_lookup_sends_original_spelling_and_preserves_multiple_candidates(self):
        value = barcode(1)
        fixture = json.dumps({'data': {'colas': [{'brand_name': 'Synthetic A'},
                                                {'brand_name': 'Synthetic B'}], 'total_colas': 2}}).encode()
        status, client, report = self.run_recipe([value], '--lookup', responses=[fixture],
                                                env={'COLA_API_KEY': 'fake-secret'})
        self.assertEqual(status, 0)
        self.assertEqual(client.requests[0].full_url, recipe.ENDPOINT + value)
        self.assertEqual(client.requests[0].get_header('Authorization'), 'Bearer fake-secret')
        self.assertEqual(report['results'][0]['returned_record_count'], 2)
        self.assertNotIn('fake-secret', json.dumps(report))

    def test_lookup_requires_key_before_client_call(self):
        self.csv.write_text('upc\n' + barcode(1) + '\n')
        client = FakeHTTP([])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            recipe.main([str(self.csv), '--lookup'], opener=client, environ={})
        self.assertEqual(client.requests, [])

    def test_404_continues_but_quota_error_stops_and_saves(self):
        errors = [urllib.error.HTTPError('fixture', code, 'sensitive body', {}, None) for code in (404, 429)]
        status, client, report = self.run_recipe([barcode(i) for i in range(1, 4)], '--lookup',
                                                responses=errors, env={'COLA_API_KEY': 'fake'})
        self.assertEqual(status, 1)
        self.assertEqual(len(client.requests), 2)
        self.assertEqual([r['status'] for r in report['results']], ['no_candidates', 'http_error'])
        self.assertNotIn('sensitive body', json.dumps(report))

    def test_invalid_response_stops_without_retry(self):
        status, client, report = self.run_recipe([barcode(1), barcode(2)], '--lookup',
                                                responses=[b'{"data":{}}'], env={'COLA_API_KEY': 'fake'})
        self.assertEqual(status, 1)
        self.assertEqual(len(client.requests), 1)
        self.assertEqual(report['results'][0]['status'], 'invalid_response')

    def test_redirect_rejected_without_forwarding_credentials(self):
        request = urllib.request.Request(recipe.ENDPOINT + barcode(1), headers={'Authorization': 'Bearer fake'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            recipe.NoRedirect().redirect_request(request, None, 302, 'found', {}, 'https://example.invalid/')
        caught.exception.close()

    def test_lookup_is_bounded_to_ten_requests(self):
        fixture = b'{"data":{"colas":[{"brand_name":"Synthetic"}]}}'
        status, client, report = self.run_recipe([barcode(i) for i in range(1, 14)], '--lookup',
                                                responses=[fixture] * 10, env={'COLA_API_KEY': 'fake'})
        self.assertEqual(status, 0)
        self.assertEqual(len(client.requests), 10)
        self.assertEqual(report['plan']['deferred_unique_strings'], 3)

    def test_network_failure_saves_partial_report_without_exception_text(self):
        status, client, report = self.run_recipe([barcode(1)], '--lookup',
                                                responses=[urllib.error.URLError('fake-secret')],
                                                env={'COLA_API_KEY': 'fake-secret'})
        self.assertEqual(status, 1)
        self.assertEqual(report['results'][0]['status'], 'network_error')
        self.assertNotIn('fake-secret', json.dumps(report))

    def test_limit_cannot_exceed_ten(self):
        with self.assertRaises(ValueError):
            recipe.plan_csv(self.csv, limit=11)


if __name__ == '__main__':
    unittest.main()
