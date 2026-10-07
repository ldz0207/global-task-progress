// Exercise the production page's ordering and preference behavior without a server.
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
  return vm.runInContext(definitions + '\n({compareRows,prefs,pinned,savePrefs,pct,count,eta})', context);
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
console.log(`Page behavior: ${checks} checks passed`);
