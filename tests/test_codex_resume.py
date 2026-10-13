import io,json,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import task_progress as progress
from codex_resume import ResumeManager,disposition,transition

def row(status='inProgress',turn='one'):
    return {'id':'example','turn_id':turn,'name':'Example task','status':status,'started_at':110}

class Desktop:
    def __init__(self,source):self.source=source;self.sent=[];self.runtime='idle';self.failure=False
    def status(self,*args,**kwargs):return {'runtime':{'type':self.runtime},'message_id':None}
    def settings(self,*args):return {'settings':{'model':'existing'}}
    def resume(self,thread,prompt,message):
        self.sent.append((thread,prompt,message))
        if self.failure:raise TimeoutError('no receipt')
        self.source[thread]=row(turn='two',status='inProgress')
    def close(self):pass

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name);self.rows={'example':row(status='interrupted')}
        self.app=Desktop(self.rows)
        self.manager=ResumeManager(self.path,{'enabled':True},reader=lambda:self.rows,session=lambda:{'key':'new','started_at':100},desktop=lambda:self.app)
        self.manager.record={'session':{'key':'new'},'active':[],'recoveries':{'example:one':row()}}
        self.manager.last_rows=self.rows
    def tearDown(self):self.manager.close();self.temp.cleanup()
    def dispatch(self):
        self.manager.request(self.manager.token);self.manager.sender.join(timeout=3)
        self.assertFalse(self.manager.sender.is_alive())
    def test_exit_captures_last_active(self):
        record={'session':{'key':'old'},'active':[row()]};transition(record,None,[],120)
        self.assertEqual(len(record['recoveries']),1)
    def test_direct_restart_keeps_checkpoint(self):
        record={'session':{'key':'old'},'active':[row()]};transition(record,{'key':'new'},[],120)
        self.assertIn('example:one',record['recoveries'])
    def test_manual_stop_not_captured(self):
        record={'session':{'key':'old'},'active':[row()]};transition(record,{'key':'old'},[],120);transition(record,None,[],122)
        self.assertEqual(record.get('recoveries',{}),{})
    def test_pending_survives_empty_later_session(self):
        record={'session':{'key':'old'},'active':[row()]};transition(record,None,[],120);transition(record,{'key':'new'},[],121);transition(record,None,[],122)
        self.assertEqual(len(record['recoveries']),1)
    def test_actual_active_required(self):
        self.manager.record={'session':{'key':'new'},'recoveries':{}};self.rows['example']=row();self.app.runtime='idle'
        self.manager.sample(self.app,{})
        self.assertEqual(self.manager.record['active'],[])
    def test_pre_start_stale_turn_excluded(self):
        self.manager.record={'session':{'key':'new'},'recoveries':{}};self.rows['example']={**row(),'started_at':10};self.app.runtime='active'
        self.manager.sample(self.app,{})
        self.assertEqual(self.manager.record['active'],[])
    def test_idle_startup_sample_is_rechecked_when_turn_becomes_active(self):
        self.manager.record={'session':{'key':'new'},'recoveries':{}};self.rows['example']=row();cache={}
        self.manager.sample(self.app,cache);self.app.runtime='active';self.manager.sample(self.app,cache)
        self.assertEqual(len(self.manager.record['active']),1)
    def test_current_active_not_a_resume_target(self):
        self.manager.record={'session':{'key':'new'},'active':[row()],'recoveries':{}};self.dispatch()
        self.assertEqual(self.app.sent,[])
    def test_sends_once_and_keeps_receipt(self):
        self.dispatch();self.dispatch();self.assertEqual(len(self.app.sent),1)
        self.assertEqual(self.manager.journal['example:one']['status'],'accepted')
        reopened=ResumeManager(self.path,{'enabled':True},reader=lambda:self.rows,session=lambda:{'key':'new','started_at':100},desktop=lambda:self.app)
        self.assertEqual(reopened.journal['example:one']['status'],'accepted');reopened.close()
    def test_completed_is_skipped(self):
        self.rows['example']=row(status='completed');self.dispatch();self.assertEqual(self.app.sent,[])
    def test_new_turn_is_skipped(self):
        self.rows['example']=row(turn='two');self.dispatch();self.assertEqual(self.app.sent,[])
    def test_running_is_skipped(self):
        self.app.runtime='active';self.dispatch();self.assertEqual(self.app.sent,[])
    def test_failed_receipt_is_not_retried(self):
        self.app.failure=True;self.dispatch();self.dispatch();self.assertEqual(len(self.app.sent),1)
        self.assertEqual(self.manager.journal['example:one']['status'],'unconfirmed')
    def test_missing_is_not_sent(self):
        self.rows.clear();self.dispatch();self.assertEqual(self.app.sent,[])
        self.assertEqual(self.manager.operation['status'],'attention')
    def test_get_snapshot_never_sends(self):
        for _ in range(5):self.manager.snapshot()
        self.assertEqual(self.app.sent,[])
    def test_wrong_token_rejected(self):
        with self.assertRaises(PermissionError):self.manager.request('wrong')
        self.assertEqual(self.app.sent,[])
    def test_disabled_does_not_start_observer(self):
        manager=ResumeManager(self.path,{'enabled':False});manager.start()
        self.assertIsNone(manager.monitor_thread);manager.close()
    def test_same_sender_reused_during_batch(self):
        event=threading.Event()
        with patch.object(self.manager,'_dispatch',side_effect=lambda:event.wait(1)):
            self.manager.request(self.manager.token);first=self.manager.sender;self.manager.request(self.manager.token)
            self.assertIs(self.manager.sender,first);event.set();first.join(2)
    def test_config_preserves_port_and_other_settings(self):
        progress.atomic(self.path/'服务配置.json',{'identity':progress.IDENTITY,'port':8790,'other':123})
        progress.configure_codex(self.path,True)
        config=progress.read(self.path/'服务配置.json');self.assertEqual(config['other'],123);self.assertEqual(config['port'],8790)

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.manager=ResumeManager(Path(self.temp.name),{'enabled':False})
    def tearDown(self):self.manager.close();self.temp.cleanup()
    def handler(self,path,headers=None,body=None):
        cls=progress.progress_handler(Path(self.temp.name),8790,self.manager);h=cls.__new__(cls)
        h.headers={'Host':'127.0.0.1:8790',**(headers or {})};h.path=path;h.codes=[]
        raw=json.dumps(body or {}).encode();h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO();h.headers.setdefault('Content-Length',str(len(raw)))
        h.send_error=lambda code,*args:h.codes.append(code);h.send_response=lambda code:h.codes.append(code)
        h.send_header=lambda *args:None;h.end_headers=lambda:None
        return h
    def test_get_contains_optional_status_and_no_action(self):
        h=self.handler('/api/tasks');h.do_GET();value=json.loads(h.wfile.getvalue());self.assertEqual(h.codes,[200]);self.assertFalse(value['codex']['enabled'])
    def test_foreign_origin_is_rejected_before_action(self):
        h=self.handler('/api/codex/resume',{'Origin':'https://unrelated.invalid'}, {'token':self.manager.token});h.do_POST();self.assertEqual(h.codes,[403])
    def test_bad_host_is_rejected(self):
        h=self.handler('/api/codex/resume',{'Host':'unrelated.invalid'}, {'token':self.manager.token});h.do_POST();self.assertEqual(h.codes,[403])
    def test_wrong_token_is_rejected(self):
        h=self.handler('/api/codex/resume',body={'token':'bad'});h.do_POST();self.assertEqual(h.codes,[403])
    def test_extra_prompt_cannot_be_submitted(self):
        h=self.handler('/api/codex/resume',body={'token':self.manager.token,'prompt':'unexpected'});h.do_POST();self.assertEqual(h.codes,[400])
    def test_disabled_is_not_a_successful_action(self):
        h=self.handler('/api/codex/resume',body={'token':self.manager.token});h.do_POST();self.assertEqual(h.codes,[409])

if __name__=='__main__':unittest.main()
