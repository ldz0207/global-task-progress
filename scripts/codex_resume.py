"""Optional, manual Codex continuation inside the existing progress server."""
import copy
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

PROMPT='继续完成本对话退出前尚未完成的原任务。先核对最后进度、已完成操作、当前文件和正在运行的后台任务，再从中断处继续；不要重复已完成的操作。沿用本对话现有的模型、设置、用户授权范围和停止条件。若已经完成，只报告结果；若仍需用户输入或批准，请明确说明并等待。'

def key(row):return row['id']+':'+row['turn_id']

def disposition(row,current,journal):
    entry=journal.get(key(row),{})
    if entry.get('status') in ('accepted','skipped'):return 'handled'
    if current is None:return 'missing'
    if current['turn_id']!=row['turn_id'] or current['status']=='completed':return 'already-continued'
    if entry.get('status') in ('sending','unconfirmed'):return 'unconfirmed'
    return 'resume'

def transition(record,session,active,now):
    old=record.get('session')
    if old and (not session or old['key']!=session['key']):
        for row in record.get('active',[]):
            record.setdefault('recoveries',{}).setdefault(key(row),{**row,'exit_session':old['key'],'captured_at':record.get('updated_at',now)})
    record.update(session=session,active=active,updated_at=now)
    return record

class ResumeManager:
    """One sampler thread and an on-demand sender, both in the same server process."""
    def __init__(self,state,settings,*,reader=None,session=None,desktop=None,progress=None):
        from task_progress import atomic, read
        self.write,self.read=atomic,read
        self.directory=Path(state)/'codex';self.directory.mkdir(parents=True,exist_ok=True)
        self.settings=settings;self.enabled=settings.get('enabled') is True
        self.token=secrets.token_urlsafe(32)
        self.lock=threading.RLock();self.stop_event=threading.Event()
        self.record=self._read('monitor.json',{'recoveries':{}});self.journal=self._read('journal.json',{})
        self.operation=self._read('operation.json',{'status':'idle','results':[]})
        if self.operation.get('status')=='running':self.operation.update(status='attention',message='上次服务退出时恢复尚未结束；将核对回合，避免重复发送。')
        self.last_rows={};self.error=None;self.checked_at=None;self.monitor_thread=None;self.sender=None
        self.reader,self.session,self.desktop=reader,session,desktop
        self.progress=progress
        if self.enabled and reader is None:
            if os.name!='nt':self.error='Codex 桌面续接目前支持 Windows。';return
            from codex_desktop import StateReader,app_session,Desktop
            self.reader=StateReader(settings.get('codex_home') or Path.home()/'.codex').rows
            self.session,self.desktop=app_session,Desktop

    def _read(self,name,default):
        path=self.directory/name
        return self.read(path) if path.exists() else copy.deepcopy(default)

    def start(self):
        if self.enabled and self.reader and self.monitor_thread is None:
            self.monitor_thread=threading.Thread(target=self._observe,name='codex-exit-recorder',daemon=True);self.monitor_thread.start()

    def sample(self,client,validated):
        session=self.session();rows=self.reader() if session else {};active=[]
        if session:
            for row in rows.values():
                if row['status']!='inProgress' or (row.get('started_at') or 0)<session['started_at']-2:continue
                identity=key(row)
                if identity not in validated:
                    try:
                        if client.status(row['id'],timeout=2)['runtime']['type']=='active':validated[identity]=True
                    except TimeoutError:continue
                if validated.get(identity):active.append({k:row.get(k) for k in ('id','name','turn_id','started_at')})
        fresh=self.session()
        if session and (not fresh or fresh['key']!=session['key']):session=fresh;active=[]
        with self.lock:
            transition(self.record,session,active,time.time());self.write(self.directory/'monitor.json',self.record)
            self.last_rows=rows;self.checked_at=time.time();self.error=None

    def _observe(self):
        client=None;epoch=None;validated={}
        try:
            while not self.stop_event.is_set():
                try:
                    current=self.session();current_key=current['key'] if current else None
                    if current_key!=epoch:
                        if client:client.close()
                        client=None;epoch=current_key;validated={}
                    if current and client is None:client=self.desktop()
                    self.sample(client,validated)
                except Exception as error:
                    with self.lock:self.error=str(error);self.checked_at=time.time()
                    if client:client.close();client=None
                self.stop_event.wait(2)
        finally:
            if client:client.close()

    def _pending(self):
        return [row for row in self.record.get('recoveries',{}).values() if disposition(row,self.last_rows.get(row['id']),self.journal) not in ('handled','already-continued')]

    def snapshot(self):
        with self.lock:
            pending=self._pending()
            return {'enabled':self.enabled,'token':self.token,'app_online':bool(self.record.get('session')),
                    'monitor_status':'error' if self.error else 'running' if self.enabled else 'disabled',
                    'message':self.error or ('记录器随进度服务运行；续接由按钮触发。' if self.enabled else ''),
                    'checked_at':self.checked_at,'running_count':len(self.record.get('active',[])),
                    'pending_count':len(pending),'pending':[{'id':r['id'],'name':r.get('name') or r['id'],'status':disposition(r,self.last_rows.get(r['id']),self.journal)} for r in pending],
                    'active':[{'id':r['id'],'name':r.get('name') or r['id']} for r in self.record.get('active',[])],
                    'operation':copy.deepcopy(self.operation)}

    def request(self,token):
        if not isinstance(token,str) or not secrets.compare_digest(token,self.token):raise PermissionError('请从本机进度页面点击续接。')
        with self.lock:
            if not self.enabled:raise RuntimeError('Codex 记录功能尚未启用。')
            if self.sender and self.sender.is_alive():return self.snapshot()
            if self.error:raise RuntimeError(self.error)
            if not self.record.get('session'):raise RuntimeError('请先重新打开 Codex，再点击续接。')
            self.operation={'id':str(uuid.uuid4()),'status':'running','stage':'核对退出前名单','done':0,'total':None,'results':[],'updated_at':time.time()}
            self.write(self.directory/'operation.json',self.operation)
            self.sender=threading.Thread(target=self._dispatch,name='codex-manual-resume',daemon=True);self.sender.start()
            return self.snapshot()

    def _update(self,**values):
        with self.lock:
            self.operation.update(values,updated_at=time.time());self.write(self.directory/'operation.json',self.operation)
            if self.progress:
                try:self.progress(copy.deepcopy(self.operation))
                except Exception as error:self.operation['progress_error']=str(error)

    def _dispatch(self):
        app=None;results=[];done=0
        try:
            rows=self.reader()
            with self.lock:
                targets=[copy.deepcopy(r) for r in self.record.get('recoveries',{}).values() if disposition(r,rows.get(r['id']),self.journal)!='handled']
            self._update(total=len(targets));app=self.desktop()
            for row in targets:
                name=row.get('name') or row['id'];current=self.reader().get(row['id']);choice=disposition(row,current,self.journal)
                self._update(stage='核对并继续',message=name,done=done,results=results)
                if choice in ('already-continued','handled'):
                    self.journal[key(row)]={'status':'skipped','reason':'已完成或已续接'};outcome='跳过：已完成或已续接'
                elif choice in ('missing','unconfirmed'):
                    outcome='需核对：对话已归档或缺失' if choice=='missing' else '需核对：上次发送未确认，未重复发送'
                else:
                    app.settings(row['id']);live=app.status(row['id'],timeout=3)
                    if live['runtime'] and live['runtime']['type']=='active':
                        self.journal[key(row)]={'status':'skipped','reason':'已经在运行'};outcome='跳过：已经在运行'
                    else:
                        message_id=str(uuid.uuid4());self.journal[key(row)]={'status':'sending','message_id':message_id,'updated_at':time.time()}
                        self.write(self.directory/'journal.json',self.journal)
                        try:
                            app.resume(row['id'],PROMPT,message_id)
                            deadline=time.monotonic()+5;confirmed=False
                            while time.monotonic()<deadline:
                                newest=self.reader().get(row['id'])
                                if newest and newest['turn_id']!=row['turn_id']:confirmed=True;break
                                self.stop_event.wait(.2)
                            if not confirmed:confirmed=app.status(row['id'],timeout=3)['message_id']==message_id
                            if not confirmed:raise RuntimeError('桌面尚未读回新回合。')
                            self.journal[key(row)]['status']='accepted';outcome='已提交继续'
                        except Exception as error:
                            self.journal[key(row)].update(status='unconfirmed',error=str(error));self.write(self.directory/'journal.json',self.journal)
                            results.append({'name':name,'result':'发送未确认：'+str(error)})
                            raise RuntimeError('发送结果未确认，本批已停止；保留收据以防重复发送。') from error
                self.write(self.directory/'journal.json',self.journal)
                done+=1;results.append({'name':name,'result':outcome})
            attention=any('需核对' in item['result'] for item in results)
            self._update(status='attention' if attention else 'complete',stage='续接检查完成',done=done,total=len(targets),results=results,message='没有待恢复对话。' if not targets else '续接检查已完成。')
        except Exception as error:self._update(status='failed',stage='续接未完成',done=done,results=results,message=str(error))
        finally:
            if app:app.close()

    def close(self):
        self.stop_event.set()
        if self.monitor_thread:self.monitor_thread.join(timeout=3)
