import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import task_progress as progress
import check_environment as env


class PortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='port-test-', dir=Path(__file__).resolve().parents[1].parent)
        self.state = Path(self.temp.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        os.environ.pop('TASK_PROGRESS_PORT', None)

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_invalid_port_is_rejected(self):
        for value in (0,65536,-1,True,2.5,'abc',None):
            with self.subTest(value=value), self.assertRaises((ValueError,TypeError)):
                progress.port_value(value)

    def test_default_http_port_accepts_browser_host_without_port(self):
        self.assertIn('127.0.0.1',progress.allowed_hosts(80))
        self.assertIn('localhost',progress.allowed_hosts(80))
        self.assertNotIn('127.0.0.1',progress.allowed_hosts(8888))
        self.assertIn('127.0.0.1:8888',progress.allowed_hosts(8888))

    def test_precedence_and_legacy_metadata(self):
        self.assertEqual(progress.resolve_port(self.state),8790)
        progress.atomic(self.state/'服务状态.json',{'identity':progress.IDENTITY,'port':8901})
        self.assertEqual(progress.resolve_port(self.state),8901)
        progress.save_port(self.state,8902)
        self.assertEqual(progress.resolve_port(self.state),8902)
        os.environ['TASK_PROGRESS_PORT']='8903'
        self.assertEqual(progress.resolve_port(self.state),8903)
        self.assertEqual(progress.resolve_port(self.state,8904),8904)

    def test_candidate_scan_skips_real_occupied_socket(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            port=listener.getsockname()[1]
            self.assertFalse(progress.port_available(port))
            self.assertNotIn(port,progress.free_ports(port,count=2))

    def test_user_choice_saved_without_starting_server(self):
        with patch.object(progress,'health',side_effect=urllib.error.URLError('refused')), patch.object(progress,'port_available',return_value=True), patch.object(progress.subprocess,'Popen') as spawn:
            result=progress.configure_port(self.state,8905)
        self.assertEqual(result['status'],'available')
        self.assertEqual(progress.resolve_port(self.state),8905)
        spawn.assert_not_called()

    def test_port_change_preserves_unrelated_configuration(self):
        progress.atomic(self.state/'服务配置.json',{'identity':progress.IDENTITY,'port':8905,'user_note':'keep'})
        progress.save_port(self.state,8906)
        self.assertEqual(progress.read(self.state/'服务配置.json')['user_note'],'keep')

    def test_busy_user_choice_keeps_previous_configuration(self):
        progress.save_port(self.state,8906)
        with patch.object(progress,'health',side_effect=urllib.error.URLError('refused')), patch.object(progress,'port_available',return_value=False), patch.object(progress.subprocess,'Popen') as spawn:
            with self.assertRaises(RuntimeError): progress.configure_port(self.state,8907)
            with self.assertRaises(RuntimeError): progress.ensure(self.state,8907)
        self.assertEqual(progress.resolve_port(self.state),8906)
        spawn.assert_not_called()

    def test_foreign_http_service_is_not_treated_as_free(self):
        with patch.object(progress.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps({'identity':'foreign','state_dir':str(self.state)}).encode())), patch.object(progress,'free_ports',return_value=[8908]), patch.object(progress,'port_available',return_value=True):
            result=progress.inspect_port(self.state,8907)
        self.assertFalse(result['ok'])
        self.assertEqual(result['available_ports'],[8908])


class CustomPortIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.environment=patch.dict(os.environ)
        cls.environment.start()
        os.environ.pop('TASK_PROGRESS_PORT',None)
        cls.temp = tempfile.TemporaryDirectory(prefix='custom-port-live-', dir=Path(__file__).resolve().parents[1].parent)
        cls.state = Path(cls.temp.name)
        candidates = progress.free_ports(19000, count=2)
        if len(candidates)<2:
            cls.temp.cleanup()
            cls.environment.stop()
            raise unittest.SkipTest('Two isolated test ports unavailable')
        cls.port,cls.other=candidates
        cls.log = (cls.state/'test-server.log').open('wb')
        cls.process = subprocess.Popen([sys.executable,'-B',progress.__file__,'serve','--state-dir',str(cls.state),'--port',str(cls.port)],stdin=subprocess.DEVNULL,stdout=cls.log,stderr=cls.log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if cls.process.poll() is not None: raise RuntimeError('Test server exited')
                try:
                    cls.health=progress.health(cls.state,cls.port)
                    return
                except urllib.error.URLError: time.sleep(.1)
            raise RuntimeError('Test server startup timed out')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        if cls.process.poll() is None:
            cls.process.terminate();cls.process.wait(timeout=5)
        cls.log.close();cls.temp.cleanup()
        cls.environment.stop()

    def test_custom_service_persists_choice_and_reuses_same_process(self):
        self.assertEqual(progress.resolve_port(self.state),self.port)
        with patch.object(progress.subprocess,'Popen') as spawn:
            result=progress.ensure(self.state)
        spawn.assert_not_called()
        self.assertEqual(result['pid'],self.process.pid)
        reporter=progress.Reporter('custom-port','端口验收',self.state)
        self.assertEqual(reporter.port,self.port)
        self.assertEqual(reporter.url,f'http://127.0.0.1:{self.port}/')
        reporter.update('底层核验',1,1,status='complete')
        with urllib.request.urlopen(reporter.url+'api/tasks',timeout=3) as response: tasks=json.load(response)['tasks']
        self.assertEqual(tasks[0]['task_id'],'custom-port')
        self.assertEqual(tasks[0]['status'],'complete')
        self.assertTrue(env.check_environment(self.state)['ready'])

    def test_live_service_blocks_a_second_port_for_same_state(self):
        with self.assertRaisesRegex(RuntimeError,'已有进度服务'):
            progress.configure_port(self.state,self.other)
        with patch.object(progress.subprocess,'Popen') as spawn, self.assertRaisesRegex(RuntimeError,'已有进度服务'):
            progress.ensure(self.state,self.other)
        spawn.assert_not_called()
        self.assertEqual(progress.resolve_port(self.state),self.port)

    def test_host_check_uses_selected_port(self):
        request=urllib.request.Request(progress.service_url(self.port)+'api/health',headers={'Host':'127.0.0.1:8790'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,403)


if __name__=='__main__':
    unittest.main()
