"""Live checker's transport protections, without external requests or real keys."""
import gzip
import io
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from tools.check_reference_api import CheckFailure, Client, NoRedirect


class Reply(io.BytesIO):
    def __init__(self, body, code=200, headers=None):
        super().__init__(body)
        self.code, self.headers = code, headers or {}


class ReferenceCheckerTests(unittest.TestCase):
    def client(self, reply):
        client = Client('https://example.test', 'x' * 40)
        client.opener = Mock()
        client.opener.open.return_value = reply
        return client

    def test_origin_validation_and_same_service_links(self):
        for origin in ('http://example.test', 'https://secret@example.test', 'https://example.test/path',
                       'https://example.test?key=value', 'https://example.test/#fragment'):
            with self.subTest(origin=origin), self.assertRaises(CheckFailure):
                Client(origin, 'x' * 40)
        client = self.client(Reply(b'{}'))
        for path in ('https://other.test/v1/a', '//other.test/v1/a', '/v1/a#fragment',
                     '/v1/a\nHeader:value', '/v1/\\other.test'):
            with self.subTest(path=path), self.assertRaises(CheckFailure):
                client.request(path)
        client.opener.open.assert_not_called()
        self.assertEqual(Client('http://127.0.0.1:8000', 'x' * 40).url, 'http://127.0.0.1:8000')

    def test_redirects_never_forward_the_key(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))
        client = self.client(Reply(b'private error body', code=302, headers={'Location': 'https://other.test'}))
        with self.assertRaises(CheckFailure) as error:
            client.request('/v1/datasets/current/summary')
        self.assertEqual(str(error.exception), 'Expected HTTP 200; received HTTP 302.')
        client.opener.open.assert_called_once()

    def test_decoded_gzip_budget_and_wire_budget(self):
        client = self.client(Reply(gzip.compress(b'x' * 100000), headers={'Content-Encoding': 'gzip'}))
        with self.assertRaisesRegex(CheckFailure, 'Decoded response'):
            client.request('/v1/test', budget=1024)
        client = self.client(Reply(b'x' * 7000))
        with self.assertRaisesRegex(CheckFailure, 'Wire response'):
            client.request('/v1/test', budget=1024)
        client = self.client(Reply(gzip.compress(b'{}'), headers={'Content-Encoding': 'gzip'}))
        self.assertEqual(client.request('/v1/test', budget=1024)[0], b'{}')

    def test_credentials_only_in_header_and_errors_are_redacted(self):
        client = self.client(Reply(b'{}'))
        client.request('/v1/test')
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.test/v1/test')
        self.assertEqual(request.get_header('Authorization'), 'Bearer ' + 'x' * 40)
        self.assertIsNone(request.data)
        client = self.client(Reply(b''))
        client.opener.open.side_effect = HTTPError('https://example.test', 503, 'SECRET REASON', {}, io.BytesIO(b'SECRET BODY'))
        with self.assertRaises(CheckFailure) as error:
            client.request('/v1/test')
        self.assertEqual(str(error.exception), 'Expected HTTP 200; received HTTP 503.')
        client = self.client(Reply(b'', code=304))
        client.request('/v1/test', expected=304, authenticate=False)
        self.assertIsNone(client.opener.open.call_args.args[0].get_header('Authorization'))


if __name__ == '__main__':
    unittest.main()
