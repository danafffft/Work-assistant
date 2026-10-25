import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        app.SESSIONS['test-session']={'mode':'desktop','store':'store','expires':time.time()+600,'csrf':'test-csrf','messages':{}}
    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        app.SESSIONS.pop('test-session',None)
    def request(self,path,data=None,csrf='test-csrf'):
        headers={'Cookie':'session=test-session','Origin':self.base,'X-CSRF-Token':csrf,'Content-Type':'application/json'}
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        with urllib.request.urlopen(req) as response: return json.load(response)
    def test_settings_are_session_only_and_plan_uses_them(self):
        settings={'url':'https://jira.example.com','email':'person@example.com','token':'test-only'}
        self.assertEqual(self.request('/api/jira-settings',settings),{'ok':True})
        with patch('desktop_outlook.calendar_events',return_value=[]),patch('integrations.jira_tasks',return_value=([{'id':'J-1','title':'Task','minutes':30}], 'Jira updated')) as jira:
            result=self.request('/api/plan')
        self.assertTrue(result['draft'])
        self.assertEqual(result['timezone'],'Europe/Kyiv')
        self.assertEqual(jira.call_args.args[1],settings)
        self.assertNotIn('test-only',json.dumps(result))
        self.assertNotIn('teams',result['sources'])
    def test_calendar_error_does_not_produce_empty_plan(self):
        with patch('desktop_outlook.calendar_events',side_effect=ValueError('failed')):
            with self.assertRaises(urllib.error.HTTPError) as error: self.request('/api/plan')
        self.assertEqual(error.exception.code,502)
    def test_settings_require_csrf(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/jira-settings',{'url':'https://jira.example.com','token':'test-only'},csrf='wrong')
        self.assertEqual(error.exception.code,403)
    def test_reject_credentials_in_url(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/jira-settings',{'url':'https://user:password@jira.example.com','token':'test-only'})
        self.assertEqual(error.exception.code,400)

    def test_profile_persists_preferences_without_token(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch('local_profile.path',return_value=Path(directory)/'profile.json'):
            result=self.request('/api/profile',{'email':'person@example.com','url':'https://example.atlassian.net','token':'secret-test-only'})
            saved=(Path(directory)/'profile.json').read_text()
            self.assertNotIn('secret-test-only', saved)
            self.assertEqual(json.loads(saved),{'email':'person@example.com','url':'https://example.atlassian.net'})
            self.assertTrue(result['jiraConnected'])
            self.assertNotIn('secret-test-only',json.dumps(result))
            self.assertEqual(self.request('/api/status')['profile']['email'],'person@example.com')

    def test_identity_change_drops_previous_token(self):
        import tempfile
        from pathlib import Path
        app.SESSIONS['test-session']['jira']={'email':'old@example.com','url':'https://example.atlassian.net','token':'old-test-token'}
        with tempfile.TemporaryDirectory() as directory, patch('local_profile.path',return_value=Path(directory)/'profile.json'):
            result=self.request('/api/profile',{'email':'new@example.com','url':'https://example.atlassian.net'})
            self.assertFalse(result['jiraConnected'])
            self.assertFalse(app.SESSIONS['test-session']['jira']['token'])
