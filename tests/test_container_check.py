"""Offline regressions for container validation; no Docker or network required."""
from contextlib import redirect_stdout
import hashlib
from http.client import RemoteDisconnected
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from tools import check_container


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.urlopen = self.enterContext(patch.object(check_container, 'urlopen'))
        self.clock = self.enterContext(patch.object(check_container.time, 'monotonic', return_value=0))
        self.sleep = self.enterContext(patch.object(check_container.time, 'sleep'))

    def test_transient_startup_errors_are_retried(self):
        ready = MagicMock()
        ready.__enter__.return_value.status = 200
        self.urlopen.side_effect = [
            ConnectionResetError(104, 'Connection reset by peer'),
            ConnectionAbortedError(), RemoteDisconnected(),
            URLError('Connection refused'), TimeoutError(), ready,
        ]
        check_container.wait_until_ready('http://localhost')
        self.assertEqual(self.urlopen.call_count, 6)
        self.assertEqual(self.sleep.call_count, 5)

    def test_persistent_resets_time_out(self):
        self.urlopen.side_effect = ConnectionResetError(104, 'Connection reset by peer')
        self.clock.side_effect = [0, 119, 120]
        with self.assertRaisesRegex(RuntimeError, 'did not become ready'):
            check_container.wait_until_ready('http://localhost')
        self.assertEqual(self.urlopen.call_count, 2)
        self.sleep.assert_called_once_with(1)

    def test_unexpected_errors_fail_immediately(self):
        self.urlopen.side_effect = ValueError('Unexpected failure')
        with self.assertRaises(ValueError):
            check_container.wait_until_ready('http://localhost')
        self.sleep.assert_not_called()


class ContainerCheckTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.lock = self.root / 'dataset.lock.json'
        # A compact lock must compare to the assembler's canonical representation.
        lock = {'manifest_sha256': 'b' * 64, 'asset': 'fixture.zip'}
        self.lock.write_text(json.dumps(lock))
        self.record = {'dataset_manifest_sha256': lock['manifest_sha256'],
                       'lock_sha256': hashlib.sha256((json.dumps(lock, indent=2) + '\n').encode()).hexdigest()}
        self.record_text = json.dumps(self.record, indent=2)
        self.image = 'sha256:' + 'a' * 64
        self.receipt, self.report = self.root / 'deployment.json', self.root / 'runtime.json'
        self.argv = ['check_container', '--image', 'fixture:mutable', '--lock', str(self.lock),
                     '--receipt', str(self.receipt), '--report', str(self.report)]
        self.enterContext(patch('sys.argv', self.argv))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.docker = self.enterContext(patch.object(check_container, 'docker', side_effect=self.fake_docker))
        self.probe = self.enterContext(patch.object(check_container, 'run_probe', return_value=12.5))
        self.memory = self.enterContext(patch.object(check_container, 'memory_readings', return_value={
            'peak_memory_bytes': 300 * 1024**2, 'memory_limit_bytes': 1024 * 1024**2}))
        self.state = {'Running': True, 'OOMKilled': False}

    def fake_docker(self, *args, **kwargs):
        if args[:2] == ('image', 'inspect'):
            return self.image if args[3] == '{{.Id}}' else 'amd64'
        if args[:2] == ('run', '--rm'): return self.record_text
        if args[:2] == ('run', '--detach'): return 'fixture-container'
        if args[0] == 'info': return '{"cpus":4,"memory_bytes":16000000000}'
        if args[0] == 'inspect': return json.dumps(self.state)
        if args[:2] == ('rm', '--force'): return ''
        raise AssertionError(args)

    def test_pins_one_image_and_writes_separate_receipt_and_measurements(self):
        self.argv.extend(['--memory-mib', '1024'])
        check_container.main()
        self.assertEqual(self.receipt.read_text(), self.record_text + '\n')
        report = json.loads(self.report.read_text())
        self.assertEqual(report['startup_seconds'], 12.5)
        self.assertEqual(report['peak_memory_bytes'], 300 * 1024**2)
        self.assertEqual(report['image_id'], self.image)
        self.assertEqual(report['network'], 'none')
        for call in self.docker.call_args_list:
            if call.args[:1] == ('run',):
                self.assertIn(self.image, call.args)
                self.assertNotIn('fixture:mutable', call.args)
            if call.args[:2] == ('run', '--detach'):
                args = call.args
                self.assertIn('--read-only', args)
                self.assertEqual(args[args.index('--network') + 1], 'none')
                self.assertEqual(args[args.index('--memory') + 1], '1024m')
                self.assertEqual(args[args.index('--memory-swap') + 1], '1024m')
                self.assertNotIn('--publish', args)
        self.docker.assert_called_with('rm', '--force', 'fixture-container')

    def test_optional_measurements_do_not_require_memory_cgroups(self):
        check_container.main()
        self.memory.assert_not_called()
        self.assertNotIn('peak_memory_bytes', json.loads(self.report.read_text()))

    def test_wrong_lock_or_dataset_fails_before_starting_service(self):
        for field in ('lock_sha256', 'dataset_manifest_sha256'):
            with self.subTest(field=field):
                record = {**self.record, field: '0' * 64}
                self.record_text = json.dumps(record)
                with self.assertRaisesRegex(AssertionError, 'Image differs'):
                    check_container.main()
                self.probe.assert_not_called()
                self.assertFalse(self.receipt.exists())

    def test_probe_failure_removes_container_without_success_artifacts(self):
        self.probe.side_effect = RuntimeError('Probe failed')
        with self.assertRaisesRegex(RuntimeError, 'Probe failed'):
            check_container.main()
        self.docker.assert_called_with('rm', '--force', 'fixture-container')
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.report.exists())

    def test_oom_or_unenforced_limit_cannot_produce_success_receipt(self):
        self.state['OOMKilled'] = True
        with self.assertRaisesRegex(AssertionError, 'exhausted memory'):
            check_container.main()
        self.state['OOMKilled'] = False
        self.argv.extend(['--memory-mib', '512'])
        with self.assertRaisesRegex(AssertionError, 'not enforced'):
            check_container.main()
        self.docker.assert_called_with('rm', '--force', 'fixture-container')
        self.assertFalse(self.receipt.exists())

    def test_report_cannot_overwrite_release_receipt(self):
        self.argv[-1] = str(self.receipt)
        with redirect_stdout(io.StringIO()), patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit): check_container.main()
        self.docker.assert_not_called()


class ProbeProcessTests(unittest.TestCase):
    def test_early_exit_or_failed_checks_are_rejected(self):
        for output in ('', 'ready\n', 'ready\nfailed\n'):
            with self.subTest(output=output):
                process = MagicMock()
                process.__enter__.return_value = process
                process.stdout = io.StringIO(output)
                process.poll.return_value = None
                with patch.object(check_container.subprocess, 'Popen', return_value=process):
                    with self.assertRaises(RuntimeError): check_container.run_probe('fixture', 0)
                process.kill.assert_called_once()

    def test_success_marker_still_requires_successful_exit(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.stdout = io.StringIO('ready\npassed\n')
        process.wait.return_value = 1
        with patch.object(check_container.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'checks failed'):
                check_container.run_probe('fixture', 0)


if __name__ == '__main__': unittest.main()
