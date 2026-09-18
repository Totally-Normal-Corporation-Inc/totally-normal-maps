"""Offline regression tests for the container smoke check's startup polling."""
from contextlib import redirect_stdout
from http.client import RemoteDisconnected
import io
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from tools import check_container


class ContainerCheckTests(unittest.TestCase):
    def setUp(self):
        self.docker = self.enterContext(patch.object(check_container, 'docker', side_effect=[
            '{}', 'fixture-container', '127.0.0.1:12345', '',
        ]))
        self.urlopen = self.enterContext(patch.object(check_container, 'urlopen'))
        self.check_service = self.enterContext(patch.object(check_container, 'check_service'))
        self.clock = self.enterContext(patch.object(check_container.time, 'monotonic', return_value=0))
        self.sleep = self.enterContext(patch.object(check_container.time, 'sleep'))
        self.enterContext(patch('sys.argv', ['check_container', '--image', 'fixture-image']))
        self.enterContext(redirect_stdout(io.StringIO()))

    def ready_response(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        return response

    def test_transient_startup_errors_are_retried_before_service_checks(self):
        self.urlopen.side_effect = [
            ConnectionResetError(104, 'Connection reset by peer'),
            ConnectionAbortedError(), RemoteDisconnected(),
            URLError('Connection refused'), TimeoutError(), self.ready_response(),
        ]
        check_container.main()
        self.assertEqual(self.urlopen.call_count, 6)
        self.assertEqual(self.sleep.call_count, 5)
        self.check_service.assert_called_once()
        self.docker.assert_called_with('rm', '--force', 'fixture-container')

    def test_persistent_resets_still_time_out_and_clean_up(self):
        self.urlopen.side_effect = ConnectionResetError(104, 'Connection reset by peer')
        self.clock.side_effect = [0, 119, 120]
        with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
            check_container.main()
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(1)
        self.check_service.assert_not_called()
        self.docker.assert_called_with('rm', '--force', 'fixture-container')

    def test_connection_failure_after_readiness_is_not_hidden(self):
        self.urlopen.return_value = self.ready_response()
        self.check_service.side_effect = ConnectionResetError(104, 'Connection reset by peer')
        with self.assertRaises(ConnectionResetError):
            check_container.main()
        self.urlopen.assert_called_once()
        self.sleep.assert_not_called()
        self.docker.assert_called_with('rm', '--force', 'fixture-container')

    def test_unexpected_errors_fail_immediately_and_clean_up(self):
        self.urlopen.side_effect = ValueError('Unexpected failure')
        with self.assertRaises(ValueError):
            check_container.main()
        self.sleep.assert_not_called()
        self.check_service.assert_not_called()
        self.docker.assert_called_with('rm', '--force', 'fixture-container')


if __name__ == '__main__': unittest.main()
