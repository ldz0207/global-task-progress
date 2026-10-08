// Exercise production ordering, preferences and freshness without a server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../scripts/progress_page.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const definitions = script.slice(0, script.indexOf('const cards=new Map();'));

function load(store = new Map()) {
  const context = vm.createContext({
    localStorage: {getItem: key => store.get(key), setItem: (key, value) => store.set(key, value)},
  });
  return vm.runInContext(definitions + '\n({compareRows,prefs,pinned,savePrefs,pct,count,eta,normalizeRefreshSeconds,staleTask,phases,rate,taskExpanded,setTaskExpanded,setAllTasksExpanded,normalizeOrder,orderedRows,moveNeighbors,moveTask,summaryStats,compactStamp,briefAlert,summaryCount,summaryPercent,splitStages,completedStagesExpanded,setCompletedStagesExpanded,overviewCounts})', context);
}
const store = new Map();
const page = load(store);
const row = (id, status, done, updated, title = id) => ({id, task:{task_id:id,status,done,total:10,updated_ts:updated,title}});
const running = row('run','running',8,200,'乙');
const attention = row('check','attention',2,100,'甲');
let checks = 0;
for (const mode of ['updated','attention','progress','name','manual']) {
  page.prefs.sort = mode;
  page.pinned.add('run');
  assert(page.compareRows(running, attention) < 0, 'Pinned task must lead in every sort');
  page.pinned.clear();
  checks++;
}
page.prefs.sort='updated'; assert(page.compareRows(running,attention)<0); checks++;
for (const mode of ['attention','progress','name']) {
  page.prefs.sort=mode; assert(page.compareRows(attention,running)<0); checks++;
}
page.prefs.sort='attention';page.pinned.add('run');page.savePrefs();
const reopened=load(store);
assert.equal(reopened.prefs.sort,'attention');assert(reopened.pinned.has('run'));checks++;
assert.equal(page.pct({done:0,total:0}),100);
assert.equal(page.pct({done:7,total:null}),null);
assert(page.count({done:7,total:null}).includes('总量待确认'));checks++;
assert(page.eta({status:'paused',eta_seconds:100}).includes('暂停'));
assert(page.eta({status:'attention',eta_seconds:100}).includes('停止估计'));checks++;
const invalid=load(new Map([['global-task-progress-ui-v1','bad-json']]));
assert.equal(invalid.prefs.sort,'updated');assert.equal(invalid.pinned.size,0);checks++;
assert.equal(page.prefs.refreshSeconds,2);assert.equal(page.prefs.compact,true);assert.equal(page.taskExpanded('new-task'),false);checks++;
for (const value of [1,2,7,300,'7',' 7 ']) {
  assert.equal(page.normalizeRefreshSeconds(value),Number(value));checks++;
}
for (const value of [0,301,1.5,'',' ',null,undefined,true,false,NaN,Infinity,'abc']) {
  assert.equal(page.normalizeRefreshSeconds(value),null);checks++;
}
page.prefs.refreshSeconds=7;page.prefs.compact=true;page.savePrefs();
const customized=load(store);
assert.equal(customized.prefs.refreshSeconds,7);assert.equal(customized.prefs.compact,true);
assert.equal(customized.prefs.sort,'attention');assert(customized.pinned.has('run'));checks++;
const legacy=load(new Map([['global-task-progress-ui-v1',JSON.stringify({sort:'name',pins:['run']})]]));
assert.equal(legacy.prefs.refreshSeconds,2);assert.equal(legacy.prefs.compact,true);
assert.equal(legacy.prefs.sort,'name');assert(legacy.pinned.has('run'));checks++;
const malformed=load(new Map([['global-task-progress-ui-v1',JSON.stringify({refreshSeconds:301,compact:'true'})]]));
assert.equal(malformed.prefs.refreshSeconds,2);assert.equal(malformed.prefs.compact,true);checks++;
const clock=Date.parse('2026-10-07T12:00:00Z');
const fresh={status:'running',updated_at:new Date(clock-90000).toISOString(),done:3,total:10,speed:2,eta_seconds:4};
assert.equal(page.staleTask(fresh,clock),fresh);checks++;
const stale=page.staleTask(fresh,clock+1);
assert.equal(stale.status,'attention');assert.equal(stale.speed,null);assert.equal(stale.eta_seconds,null);
assert.equal(stale.done,3);assert.equal(fresh.status,'running');assert.equal(fresh.speed,2);
assert.equal(page.staleTask(stale,clock+300000),stale);checks++;
for (const updated_at of [undefined,'invalid']) {
  assert.equal(page.staleTask({...fresh,updated_at},clock).status,'attention');checks++;
}
for (const status of ['complete','paused','failed','cancelled']) {
  const task={...fresh,status};assert.equal(page.staleTask(task,clock+300000),task);checks++;
}
const expiredPhases=page.phases({...stale,stage:'校验',unit:'份',stages:[
  {stage:'复制',status:'complete',done:10,total:10},
  {stage:'校验',status:'running',done:3,total:10,speed:2,eta_seconds:4},
]});
assert.equal(expiredPhases[0].status,'complete');assert.equal(expiredPhases[1].status,'attention');
assert(page.rate(expiredPhases[1]).includes('停止测量'));
assert(page.eta(expiredPhases[1]).includes('停止估计'));checks++;
const detailStore=new Map([['global-task-progress-ui-v1',JSON.stringify({compact:true,sort:'name',pins:['run'],refreshSeconds:7})]]);
const details=load(detailStore);
assert.equal(details.taskExpanded('run'),false);assert.equal(details.taskExpanded('check'),false);checks++;
details.setTaskExpanded('run',true);
assert.equal(details.taskExpanded('run'),true);assert.equal(details.taskExpanded('check'),false);checks++;
details.savePrefs();
const detailReopened=load(detailStore);
assert.equal(detailReopened.taskExpanded('run'),true);assert.equal(detailReopened.taskExpanded('check'),false);
assert.equal(detailReopened.prefs.sort,'name');assert.equal(detailReopened.prefs.refreshSeconds,7);assert(detailReopened.pinned.has('run'));checks++;
details.setTaskExpanded('check',true);details.setTaskExpanded('run',false);
assert.equal(details.taskExpanded('run'),false);assert.equal(details.taskExpanded('check'),true);checks++;
details.setAllTasksExpanded(true);
assert.equal(details.taskExpanded('run'),true);assert.equal(details.taskExpanded('check'),true);assert.equal(details.taskExpanded('new-task'),true);
assert.equal(Object.keys(details.prefs.expanded).length,0);checks++;
details.setTaskExpanded('run',false);details.setAllTasksExpanded(false);
assert.equal(details.taskExpanded('run'),false);assert.equal(details.taskExpanded('check'),false);assert.equal(details.taskExpanded('new-task'),false);checks++;
details.savePrefs();
assert.equal(load(detailStore).taskExpanded('new-task'),false);
assert.equal(details.prefs.refreshSeconds,7);assert.equal(details.prefs.sort,'name');assert(details.pinned.has('run'));checks++;
details.setTaskExpanded('__proto__',true);details.savePrefs();
assert.equal(load(detailStore).taskExpanded('__proto__'),true);assert.equal(details.taskExpanded('toString'),false);checks++;
const invalidDetails=load(new Map([['global-task-progress-ui-v1',JSON.stringify({viewVersion:2,expanded:{run:true,check:'false',other:1}})]]));
assert.equal(invalidDetails.taskExpanded('run'),true);assert.equal(Object.keys(invalidDetails.prefs.expanded).length,1);checks++;
const moveStore=new Map();
const manual=load(moveStore);
const jobs=[row('a','running',2,300),row('b','paused',4,200),row('c','attention',6,100),row('h1','complete',10,400),row('h2','cancelled',3,500)].map(row=>row.task);
const ids=(rows)=>Array.from(rows,row=>row.id);
const currentIds=(page,tasks)=>ids(page.orderedRows(tasks).filter(row=>!['complete','cancelled','failed','idle'].includes(row.task.status)));
assert.deepEqual(currentIds(manual,jobs),['a','b','c']);checks++;
assert.equal(manual.moveTask(jobs,'b','up'),true);
assert.equal(manual.prefs.sort,'manual');assert.deepEqual(currentIds(manual,jobs),['b','a','c']);checks++;
assert.equal(manual.moveTask(jobs,'b','up'),false);assert.equal(manual.moveTask(jobs,'c','down'),false);
assert.equal(manual.moveTask(jobs,'missing','up'),false);assert.equal(manual.moveTask(jobs,'a','sideways'),false);checks++;
assert.equal(manual.moveTask(jobs,'b','down'),true);assert.deepEqual(currentIds(manual,jobs),['a','b','c']);checks++;
manual.setTaskExpanded('b',false);manual.prefs.refreshSeconds=7;manual.savePrefs();
const manualReopened=load(moveStore);
assert.equal(manualReopened.prefs.sort,'manual');assert.deepEqual(currentIds(manualReopened,jobs.slice().reverse()),['a','b','c']);
assert.equal(manualReopened.taskExpanded('b'),false);assert.equal(manualReopened.prefs.refreshSeconds,7);checks++;
const changedTimes=jobs.map(task=>({...task,updated_ts:task.task_id==='c'?10000:1}));
assert.deepEqual(currentIds(manualReopened,changedTimes),['a','b','c']);checks++;
const newcomer=row('new','running',0,20000).task;
assert.deepEqual(currentIds(manualReopened,[newcomer,...changedTimes]),['a','b','c','new']);checks++;
assert.deepEqual(currentIds(load(moveStore),[newcomer,...jobs]),['a','b','c','new']);checks++;
assert.deepEqual(currentIds(manualReopened,jobs.filter(task=>task.task_id!=='b')),['a','c']);
assert.deepEqual(currentIds(manualReopened,jobs),['a','b','c']);checks++;
const beforeHistory=currentIds(manualReopened,jobs);
assert.equal(manualReopened.moveTask(jobs,'h1','up'),true);
assert.deepEqual(ids(manualReopened.orderedRows(jobs).filter(row=>['complete','cancelled'].includes(row.task.status))),['h1','h2']);
assert.deepEqual(currentIds(manualReopened,jobs),beforeHistory);checks++;
manualReopened.pinned.add('b');
assert.deepEqual(currentIds(manualReopened,jobs),['b','a','c']);
assert.equal(manualReopened.moveTask(jobs,'b','down'),false);assert.equal(manualReopened.moveTask(jobs,'a','up'),false);checks++;
manualReopened.pinned.add('c');
assert.equal(manualReopened.moveTask(jobs,'c','up'),true);assert.deepEqual(currentIds(manualReopened,jobs),['c','b','a']);checks++;
manualReopened.pinned.add('h2');
assert.equal(manualReopened.moveTask(jobs,'h2','down'),false);assert.equal(manualReopened.moveTask(jobs,'h1','up'),false);
assert.deepEqual(currentIds(manualReopened,jobs),['c','b','a']);checks++;
manualReopened.prefs.sort='updated';
assert.deepEqual(currentIds(manualReopened,jobs),['b','c','a']);
manualReopened.prefs.sort='manual';assert.deepEqual(currentIds(manualReopened,jobs),['c','b','a']);checks++;
manualReopened.pinned.clear();
const completedB=jobs.map(task=>task.task_id==='b'?{...task,status:'complete'}:task);
assert.deepEqual(currentIds(manualReopened,completedB),['a','c']);
const neighbors=manualReopened.moveNeighbors(manualReopened.orderedRows(completedB));
assert.equal(neighbors.get('a').up,undefined);assert.equal(neighbors.get('a').down,'c');assert.equal(neighbors.get('c').down,undefined);checks++;
const malformedOrder=load(new Map([['global-task-progress-ui-v1',JSON.stringify({sort:'manual',order:['b',null,'b',1,'a','__proto__']})]]));
assert.deepEqual(Array.from(malformedOrder.prefs.order),['b','a','__proto__']);assert.deepEqual(currentIds(malformedOrder,jobs),['b','a','c']);checks++;
assert.deepEqual(Array.from(legacy.prefs.order),[]);
assert.deepEqual(Array.from(manual.normalizeOrder({a:1})),[]);checks++;
const invalidMove=load(new Map([['global-task-progress-ui-v1',JSON.stringify({sort:'updated'})]]));
assert.equal(invalidMove.moveTask(jobs,'a','up'),false);assert.equal(invalidMove.prefs.sort,'updated');checks++;
const temporarilyAbsent=load(new Map([['global-task-progress-ui-v1',JSON.stringify({sort:'manual',order:['a','b','c']})]]));
assert.equal(temporarilyAbsent.moveTask(jobs.filter(task=>task.task_id!=='b'),'a','down'),true);
assert.deepEqual(currentIds(temporarilyAbsent,jobs),['c','b','a']);checks++;
const oldViewStore=new Map([['global-task-progress-ui-v1',JSON.stringify({compact:false,expanded:{run:true},sort:'manual',order:['check','run'],pins:['run'],refreshSeconds:7})]]);
const migratedView=load(oldViewStore);
assert.equal(migratedView.taskExpanded('run'),false);assert.equal(migratedView.taskExpanded('check'),false);
assert.equal(migratedView.prefs.sort,'manual');assert.deepEqual(Array.from(migratedView.prefs.order),['check','run']);
assert(migratedView.pinned.has('run'));assert.equal(migratedView.prefs.refreshSeconds,7);
assert.equal(JSON.parse(oldViewStore.get('global-task-progress-ui-v1')).viewVersion,2);checks++;
migratedView.setTaskExpanded('run',true);migratedView.savePrefs();
assert.equal(load(oldViewStore).taskExpanded('run'),true);assert.equal(load(oldViewStore).taskExpanded('check'),false);checks++;
const expandedView=load(new Map([['global-task-progress-ui-v1',JSON.stringify({viewVersion:2,compact:false,expanded:{run:false}})]]));
assert.equal(expandedView.taskExpanded('run'),false);assert.equal(expandedView.taskExpanded('new-task'),true);checks++;
const measured={status:'running',done:4,total:10,unit:'份',speed:2,eta_seconds:3};
assert.equal(page.summaryStats(measured).speed,'120 份/分钟');assert.equal(page.summaryStats(measured).time,'3 秒');checks++;
for(const status of ['paused','attention','error','failed','complete','cancelled','idle']){
  const stats=page.summaryStats({...measured,status});
  assert.equal(stats.speed,null);assert(!String(stats.time).includes('3 秒'));checks++;
}
for(const speed of [null,0,-1]){
  assert.equal(page.summaryStats({...measured,speed}).time,'待估');checks++;
}
assert.equal(page.summaryStats({...measured,total:null}).time,'待估');checks++;
assert.equal(page.summaryStats({...measured,done:10}).time,'等待后续验收');checks++;
assert.equal(page.summaryStats({...measured,eta_seconds:-1}).time,'待估');checks++;
const beijingClock=Date.parse('2026-10-08T06:00:00Z');
assert.equal(page.compactStamp('2026-10-07T17:00:00Z',beijingClock),'更新 01:00:00');checks++;
assert(page.compactStamp('2026-10-07T06:00:00Z',beijingClock).includes('10/7'));checks++;
for(const value of [undefined,'','invalid']){assert.equal(page.compactStamp(value,beijingClock),'更新待确认');checks++;}
assert.equal(page.briefAlert({status:'running',message:'long technical notes'}),'');
assert.equal(page.briefAlert({status:'paused',message:'需要确认\ntechnical details'}),'需要确认');
assert(page.briefAlert({status:'attention',message:'很'.repeat(200)}).length<=90);checks++;
assert.equal(page.briefAlert({status:'attention',message:'technical notes',updated_at:new Date(beijingClock-90001).toISOString()},beijingClock),'超过90秒未更新');checks++;
assert.equal(page.briefAlert({status:'error',message:'外部进度无法读取：<urlopen error timed out>'}),'暂时无法获取进度');checks++;
assert.equal(page.summaryCount({done:null,total:null}),'等待进度');
assert(page.summaryCount({done:7,total:null,unit:'份'}).includes('已完成 7 份'));
assert.equal(page.summaryCount({done:7,total:10,unit:'份'}),'7 / 10 份');checks++;
for(const status of ['error','failed','attention']){assert.equal(page.summaryPercent({done:0,total:0,status}),null);assert.equal(page.summaryCount({done:0,total:0,status}),'等待进度');checks++;}
assert.equal(page.summaryPercent({done:0,total:0,status:'complete'}),100);checks++;
const stageFixture=(completedCount)=>({stage:'current',status:'running',unit:'份',stages:[
  ...Array.from({length:completedCount},(_,index)=>({stage:'done-'+index,status:'complete',done:1,total:1})),
  {stage:'current',status:'running',done:1,total:3},
]});
const folded=load();
for(const count of [0,1,8,9,10,40]){
  const groups=folded.splitStages(stageFixture(count));
  assert.equal(groups.completed.length,count);assert.equal(groups.visible.length,1);
  assert.equal(groups.visible[0].stage,'current');
  assert.equal(folded.completedStagesExpanded('job',count),count<=8);checks++;
}
const mixed=stageFixture(9);
mixed.stages.push({stage:'100-percent-unverified',status:'running',done:2,total:2},
 {stage:'paused-stage',status:'paused',done:0,total:2},
 {stage:'old-interruption',status:'failed',done:1,total:2},
 {stage:'queued',status:'running',done:0,total:2});
const mixedGroups=folded.splitStages(mixed);
assert.equal(mixedGroups.completed.length,9);
assert.deepEqual(Array.from(mixedGroups.visible,s=>s.stage),['current','100-percent-unverified','paused-stage','old-interruption','queued']);checks++;
const currentComplete=stageFixture(9);currentComplete.stages.at(-1).status='complete';
assert.equal(folded.splitStages(currentComplete).visible[0].stage,'current');
assert.equal(folded.splitStages(currentComplete).completed.length,9);checks++;
assert.equal(folded.completedStagesExpanded('job',8),true);
assert.equal(folded.completedStagesExpanded('job',9),false);checks++;
const completedStore=new Map();
const choices=load(completedStore);
choices.setCompletedStagesExpanded('job',true);
assert.equal(choices.completedStagesExpanded('job',9),true);
assert.equal(choices.completedStagesExpanded('job',40),true);
assert.equal(choices.completedStagesExpanded('other-job',9),false);checks++;
choices.setCompletedStagesExpanded('other-job',false);
assert.equal(choices.completedStagesExpanded('other-job',3),false);checks++;
choices.prefs.refreshSeconds=7;choices.prefs.sort='manual';choices.pinned.add('job');choices.savePrefs();
const reopenedCompleted=load(completedStore);
assert.equal(reopenedCompleted.completedStagesExpanded('job',40),true);
assert.equal(reopenedCompleted.completedStagesExpanded('other-job',3),false);
assert.equal(reopenedCompleted.prefs.refreshSeconds,7);assert.equal(reopenedCompleted.prefs.sort,'manual');assert(reopenedCompleted.pinned.has('job'));checks++;
reopenedCompleted.setAllTasksExpanded(true);
assert.equal(reopenedCompleted.completedStagesExpanded('other-job',40),false);
assert.equal(reopenedCompleted.completedStagesExpanded('new-job',9),false);
reopenedCompleted.setAllTasksExpanded(false);
assert.equal(reopenedCompleted.completedStagesExpanded('job',40),true);checks++;
choices.setCompletedStagesExpanded('__proto__',true);choices.savePrefs();
assert.equal(load(completedStore).completedStagesExpanded('__proto__',9),true);
assert.equal(load(completedStore).completedStagesExpanded('toString',9),false);checks++;
const badCompleted=load(new Map([['global-task-progress-ui-v1',JSON.stringify({viewVersion:2,completedExpanded:{good:true,bad:'true',other:1}})]]));
assert.equal(badCompleted.completedStagesExpanded('good',9),true);
assert.equal(badCompleted.completedStagesExpanded('bad',9),false);
assert.equal(Object.keys(badCompleted.prefs.completedExpanded).length,1);checks++;
const totals=page.overviewCounts(['running','paused','attention','error','failed','complete','cancelled','idle','unknown'].map(status=>({status})));
assert.equal(totals.total,9);assert.equal(totals.running,1);assert.equal(totals.waiting,5);assert.equal(totals.complete,1);checks++;
const overdue=page.staleTask({status:'running',updated_at:new Date(beijingClock-90001).toISOString()},beijingClock);
const staleTotals=page.overviewCounts([overdue,{status:'complete'}]);
assert.equal(staleTotals.running,0);assert.equal(staleTotals.waiting,1);assert.equal(staleTotals.complete,1);checks++;
const nestedTotals=page.overviewCounts([{...stageFixture(40),status:'running'},{status:'complete'}]);
assert.equal(nestedTotals.total,2);assert.equal(nestedTotals.complete,1);assert.equal(nestedTotals.running,1);checks++;
assert.equal(page.overviewCounts([]).total,0);assert.equal(page.overviewCounts([]).waiting,0);checks++;
console.log(`Page behavior: ${checks} checks passed`);
