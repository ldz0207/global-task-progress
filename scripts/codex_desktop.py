"""Local Codex desktop IPC client. Does not start another app-server or change settings."""
import ctypes
from ctypes import wintypes as w
import json, struct, time, uuid, sqlite3
from pathlib import Path

k=ctypes.WinDLL('kernel32',use_last_error=True)
k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]; k.CreateFileW.restype=w.HANDLE
k.PeekNamedPipe.argtypes=[w.HANDLE,w.LPVOID,w.DWORD,w.LPVOID,ctypes.POINTER(w.DWORD),w.LPVOID]
k.ReadFile.argtypes=[w.HANDLE,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD),w.LPVOID]
k.WriteFile.argtypes=k.ReadFile.argtypes; k.CloseHandle.argtypes=[w.HANDLE]

class Pipe:
    def __init__(self,path=r'\\.\pipe\codex-ipc'):
        self.handle=k.CreateFileW(path,0xC0000000,0,None,3,0,None)
        if self.handle==w.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
        self.buffer=bytearray()
    def send(self,msg):
        raw=json.dumps(msg,ensure_ascii=True).encode('utf-8')
        frame=struct.pack('<I',len(raw))+raw; n=w.DWORD(); buf=ctypes.create_string_buffer(frame)
        if not k.WriteFile(self.handle,buf,len(frame),ctypes.byref(n),None): raise ctypes.WinError(ctypes.get_last_error())
        if n.value!=len(frame): raise OSError('IPC frame was only partially written')
    def receive(self,timeout=15):
        end=time.monotonic()+timeout
        while True:
            if len(self.buffer)>=4:
                size=struct.unpack('<I',self.buffer[:4])[0]
                if size==0 or size>268435456: raise ValueError('Invalid Codex IPC frame size')
                if len(self.buffer)>=size+4:
                    raw=bytes(self.buffer[4:4+size]);del self.buffer[:size+4];return json.loads(raw)
            av=w.DWORD()
            if not k.PeekNamedPipe(self.handle,None,0,None,ctypes.byref(av),None): raise ctypes.WinError(ctypes.get_last_error())
            if av.value:
                buf=ctypes.create_string_buffer(min(av.value,1048576));n=w.DWORD()
                if not k.ReadFile(self.handle,buf,len(buf),ctypes.byref(n),None):raise ctypes.WinError(ctypes.get_last_error())
                self.buffer.extend(buf.raw[:n.value]);continue
            if time.monotonic()>=end: raise TimeoutError('Codex desktop IPC timed out')
            time.sleep(.025)
    def close(self):
        if self.handle is not None:k.CloseHandle(self.handle);self.handle=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class Desktop:
    def __init__(self,pipe=None):
        self.pipe=pipe or Pipe();self.client_id='uninitialized'
        try:
            r=self.request('initialize',{'clientType':'codex-oneclick-resume'},version=0)
            self.client_id=r['clientId']
        except Exception:self.pipe.close();raise
    def request(self,method,params,version=1,timeout=25):
        req=str(uuid.uuid4())
        self.pipe.send({'type':'request','requestId':req,'sourceClientId':self.client_id,'method':method,'params':params,'version':version,'timeoutMs':int(timeout*1000)})
        end=time.monotonic()+timeout
        while True:
            msg=self.pipe.receive(max(.01,end-time.monotonic()))
            if msg.get('type')=='client-discovery-request':
                self.pipe.send({'type':'client-discovery-response','requestId':msg['requestId'],'response':{'canHandle':False}})
            if msg.get('type')=='response' and msg.get('requestId')==req:
                if msg.get('resultType')!='success':raise RuntimeError(str(msg.get('error','Desktop rejected request')))
                return msg.get('result')
    def settings(self,thread_id):
        return self.request('thread-follower-read-model-settings',{'conversationId':thread_id},version=1)
    def broadcast(self,method,params,version=1):
        self.pipe.send({'type':'broadcast','sourceClientId':self.client_id,'method':method,'params':params,'version':version})
    def status(self,thread_id,timeout=3):
        params={'conversationId':thread_id,'hostId':'local','following':True}
        self.broadcast('thread-stream-following-changed',params)
        end=time.monotonic()+timeout
        try:
            while True:
                msg=self.pipe.receive(max(.01,end-time.monotonic()))
                if msg.get('type')=='client-discovery-request':
                    self.pipe.send({'type':'client-discovery-response','requestId':msg['requestId'],'response':{'canHandle':False}})
                if msg.get('method')=='thread-stream-state-changed' and msg.get('params',{}).get('conversationId')==thread_id:
                    change=msg['params'].get('change',{})
                    if change.get('type')=='snapshot':
                        state=change['conversationState']
                        turns=state.get('turns',[])
                        return {'runtime':state.get('threadRuntimeStatus'),'message_id':state.get('latestTurnStartMessageId'),'lastTurn':{k:turns[-1].get(k) for k in ('id','status')} if turns else None}
        finally:
            self.broadcast('thread-stream-following-changed',{**params,'following':False})
    def resume(self,thread_id,prompt,message_id):
        return self.request('thread-follower-start-turn',{'conversationId':thread_id,'turnStart':{'request':{'threadId':thread_id,'input':[{'type':'text','text':prompt}],'clientUserMessageId':message_id},'context':{'inheritThreadSettings':True}}},version=2,timeout=45)
    def close(self):self.pipe.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

class Entry(ctypes.Structure):
    _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('th32ProcessID',w.DWORD),('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',w.DWORD),('cntThreads',w.DWORD),('th32ParentProcessID',w.DWORD),('pcPriClassBase',w.LONG),('dwFlags',w.DWORD),('szExeFile',w.WCHAR*260)]

k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE
k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes
k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
k.GetProcessTimes.argtypes=[w.HANDLE,ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME),ctypes.POINTER(w.FILETIME)]

def app_session():
    """Identify the user's installed desktop instance by PID and creation time."""
    handle=k.CreateToolhelp32Snapshot(2,0)
    if handle==w.HANDLE(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        row=Entry();row.dwSize=ctypes.sizeof(row);rows=[];ok=k.Process32FirstW(handle,ctypes.byref(row))
        while ok:
            if row.szExeFile.lower()=='chatgpt.exe':rows.append((row.th32ProcessID,row.th32ParentProcessID))
            ok=k.Process32NextW(handle,ctypes.byref(row))
        ids={pid for pid,_ in rows}
        for pid,parent in rows:
            if parent in ids:continue
            process=k.OpenProcess(0x1000,False,pid)
            if not process:continue
            try:
                text=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(text))
                if not k.QueryFullProcessImageNameW(process,0,text,ctypes.byref(size)):continue
                if 'openai.codex_' not in text.value.lower():continue
                created,exit_time,cpu,user=(w.FILETIME() for _ in range(4))
                if not k.GetProcessTimes(process,ctypes.byref(created),ctypes.byref(exit_time),ctypes.byref(cpu),ctypes.byref(user)):continue
                ticks=(created.dwHighDateTime<<32)|created.dwLowDateTime
                return {'key':str(pid)+':'+str(ticks),'pid':pid,'started_at':ticks/10000000-11644473600}
            finally:k.CloseHandle(process)
        return None
    finally:k.CloseHandle(handle)

class StateReader:
    def __init__(self,codex_home):self.home=Path(codex_home)
    def rows(self):
        database=sqlite3.connect((self.home/'state_5.sqlite').as_uri()+'?mode=ro',uri=True,timeout=3)
        database.row_factory=sqlite3.Row
        try:
            database.execute('attach database ? as h',((self.home/'thread_history_1.sqlite').as_uri()+'?mode=ro',))
            # One aggregate scan, rather than a correlated scan for every historical turn.
            sql='''WITH last AS (SELECT thread_id,max(rollout_ordinal) AS ordinal FROM h.thread_turns GROUP BY thread_id)
            SELECT t.id,t.name,t.title,x.turn_id,x.status,x.started_at,x.completed_at
            FROM threads t JOIN last ON last.thread_id=t.id
            JOIN h.thread_turns x ON x.thread_id=t.id AND x.rollout_ordinal=last.ordinal
            WHERE t.archived=0 AND t.source='vscode' AND t.agent_path IS NULL
            AND coalesce(t.thread_source,'user') NOT IN ('guardian_review','subagent')
            AND NOT EXISTS(SELECT 1 FROM thread_spawn_edges s WHERE s.child_thread_id=t.id)'''
            return {row['id']:dict(row) for row in database.execute(sql)}
        finally:database.close()
