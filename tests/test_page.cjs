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
  return vm.runInContext(definitions + '\n({compareRows,prefs,pinned,savePrefs,pct,count,eta,normalizeRefreshSeconds,staleTask,phases,rate})', context);
}
const store = new Map();
const page = load(store);
const row = (id, status, done, updated, title = id) => ({id, task:{task_id:id,status,done,total:10,updated_ts:updated,title}});
const running = row('run','running',8,200,'乙');
const attention = row('check','attention',2,100,'甲');
let checks = 0;
for (const mode of ['updated','attention','progress','name']) {
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
assert.equal(page.prefs.refreshSeconds,2);assert.equal(page.prefs.compact,false);checks++;
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
assert.equal(legacy.prefs.refreshSeconds,2);assert.equal(legacy.prefs.compact,false);
assert.equal(legacy.prefs.sort,'name');assert(legacy.pinned.has('run'));checks++;
const malformed=load(new Map([['global-task-progress-ui-v1',JSON.stringify({refreshSeconds:301,compact:'true'})]]));
assert.equal(malformed.prefs.refreshSeconds,2);assert.equal(malformed.prefs.compact,false);checks++;
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
console.log(`Page behavior: ${checks} checks passed`);
