import {test, beforeEach, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker, {nextOccurrence} from '../worker.js';

let db, env, sent, originalFetch, sequence;
const eventId='a'.repeat(32);
const event=(changes={}) => ({id:eventId,language:'en',title:'Concert <test>',summary:'Summary',
  url:'https://example.com/event',venue:'G Livelab',municipality:'Tampere',start:'2099-10-15T17:00:00Z',
  end:'2099-10-15T19:00:00Z',dates:[],date_only:false,cancelled:false,...changes});
class D1 {
  constructor(db){this.db=db;}
  prepare(sql){
    const db=this.db;let values=[];
    return {bind(...args){values=args;return this;},
      async first(){return db.prepare(sql).get(...values) || null;},
      async all(){return {results:db.prepare(sql).all(...values)};},
      async run(){return {meta:db.prepare(sql).run(...values)};}};
  }
  async batch(statements){
    this.db.exec('BEGIN');
    try {const results=[];for(const statement of statements) results.push(await statement.run());this.db.exec('COMMIT');return results;}
    catch(error){this.db.exec('ROLLBACK');throw error;}
  }
}
beforeEach(()=>{
  db=new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../migrations/0001_favourites.sql',import.meta.url),'utf8'));
  env={DB:new D1(db),FAVOURITES_SYNC_SECRET:'sync-secret',TELEGRAM_WEBHOOK_SECRET:'webhook-secret',TELEGRAM_BOT_TOKEN:'test-token'};
  sent=[];originalFetch=globalThis.fetch;
  sequence=0;
  globalThis.fetch=async(url,options)=>{sent.push({method:url.split('/').at(-1),...JSON.parse(options.body)});return Response.json({ok:true,result:{message_id:sent.length}});};
});
afterEach(()=>{globalThis.fetch=originalFetch;db.close();});
async function request(path,body,auth=true){
  return worker.fetch(new Request('https://worker.example'+path,{method:'POST',headers:auth ?
    path==='/events' ? {Authorization:'Bearer sync-secret'} : {'X-Telegram-Bot-Api-Secret-Token':'webhook-secret'} : {},body:JSON.stringify(body)}),env);
}
async function update(user,text){return request('/telegram',{update_id:++sequence,message:{from:{id:user,language_code:'en'},chat:{id:user,type:'private'},text}});}
async function callback(user,data,chat=user){return request('/telegram',{update_id:++sequence,callback_query:{id:'query',from:{id:user},data,message:{chat:{id:chat,type:'private'}}}});}
async function register(changes={}){assert.equal((await request('/events',event(changes))).status,200);}

test('both write routes require distinct authentication and malformed bodies are refused',async()=>{
  assert.equal((await request('/events',event(),false)).status,401);
  assert.equal((await request('/telegram',{update_id:1},false)).status,401);
  assert.equal((await request('/events',event({url:'javascript:alert(1)'}))).status,400);
  assert.equal((await request('/events',event({url:'https://user:secret@example.com'}))).status,400);
  assert.equal((await request('/events',event({end:'bad'}))).status,400);
  assert.equal((await request('/events',event({date_only:'false'}))).status,400);
  assert.equal((await request('/events',event({dates:[{start:'2099-10-15',end:'2099-10-14'}]}))).status,400);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM events').get().n,0);
});
test('favourites are private, duplicate saves are idempotent, removing only affects sender',async()=>{
  await register();
  for(const user of [101,202,101]) assert.equal((await update(user,`/start save_en_${eventId}`)).status,200);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,2);
  await callback(101,`remove_en_${eventId}`);
  assert.equal(db.prepare('SELECT user_id FROM favourites').get().user_id,'202');
  await update(101,'/events');assert.match(sent.at(-1).text,/no saved/);
  await update(202,'/events');assert.match(sent.at(-1).text,/Concert &lt;test&gt;/);
  assert.equal(sent.at(-1).chat_id,'202');
});
test('forged private chat identity and channel interactions are ignored',async()=>{
  await register();await update(202,`/start save_en_${eventId}`);
  await callback(101,`remove_en_${eventId}`,202);
  await request('/telegram',{update_id:3,message:{from:{id:101},chat:{id:-100,type:'channel'},text:`/start save_en_${eventId}`}});
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,1);
});
test('expired cancelled and missing events cannot be saved',async()=>{
  await update(101,`/start save_en_${eventId}`);assert.match(sent.at(-1).text,/unavailable/);
  await register({cancelled:true});await update(101,`/start save_en_${eventId}`);
  await register({start:'2020-10-15',end:'2020-10-16',date_only:true});await update(101,`/start save_en_${eventId}`);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,0);
});
test('translations share a favourite and catalogue changes are reflected in list',async()=>{
  await register();await register({language:'ru',title:'Концерт'});
  await update(101,`/start save_en_${eventId}`);await update(101,`/start save_ru_${eventId}`);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,1);
  assert.equal(db.prepare('SELECT language FROM favourites').get().language,'ru');
  await register({cancelled:true,title:'Changed'});await update(101,'/events');
  assert.match(sent.at(-1).text,/Changed/);assert.match(sent.at(-1).text,/Cancelled/);
});
test('delete requires confirmation and deletes only the requesting user',async()=>{
  await register();for(const u of [101,202])await update(u,`/start save_en_${eventId}`);
  await update(101,'/delete_me');assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,2);
  await callback(101,'delete_en');assert.equal(db.prepare('SELECT user_id FROM favourites').get().user_id,'202');
});
test('pagination orders upcoming recurring dates and keeps messages bounded',async()=>{
  for(let n=0;n<6;n++) {
    const id=n.toString(16).padStart(32,'0');
    await register({id,title:'🎵'.repeat(90),summary:'<'.repeat(100),start:`2099-10-${15+n}T17:00:00Z`,end:`2099-10-${15+n}T19:00:00Z`});
    await update(101,`/start save_en_${id}`);
  }
  await update(101,'/events');const first=sent.at(-1);
  assert.equal(first.reply_markup.inline_keyboard.length,6);
  assert.match(first.text,/1\/2/);assert.ok(first.text.replace(/&lt;/g,'<').length<4096);
  await callback(101,'list_en_1');assert.match(sent.at(-1).text,/2\/2/);
});
test('recurring dates ignore completed occurrences and date-only uses Helsinki day',()=>{
  assert.equal(nextOccurrence({start:'2020-01-01',end:'2099-01-01',dates:[{start:'2020-01-01',end:'2020-01-02'},{start:'2099-01-01',end:'2099-01-02'}],date_only:false}).start,'2099-01-01');
  const allDay={start:'2026-10-11',end:'2026-10-11',dates:[],date_only:true};
  assert.ok(nextOccurrence(allDay,new Date('2026-10-11T20:59:59Z')));
  assert.equal(nextOccurrence(allDay,new Date('2026-10-11T21:00:00Z')),null);
});
test('capacity protects a user list without blocking duplicate saves',async()=>{
  await register();
  for(let n=0;n<100;n++) {
    const id=n.toString(16).padStart(32,'0');await register({id});
    db.prepare('INSERT INTO favourites VALUES(?,?,?)').run('101',id,'en');
  }
  await update(101,`/start save_en_${eventId}`);assert.match(sent.at(-1).text,/full/);
  await update(101,`/start save_en_${'0'.repeat(32)}`);assert.match(sent.at(-1).text,/Saved/);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,100);
});
test('Telegram failures return retryable status without losing saved data',async()=>{
  await register();globalThis.fetch=async()=>Response.json({ok:false},{status:500});
  assert.equal((await update(101,`/start save_en_${eventId}`)).status,503);
  globalThis.fetch=async()=>Response.json({ok:true,result:{}});
  assert.equal((await update(101,`/start save_en_${eventId}`)).status,200);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,1);
});
test('completed webhook replay does not resend a confirmation',async()=>{
  await register();
  const body={update_id:999,message:{from:{id:101},chat:{id:101,type:'private'},text:`/start save_en_${eventId}`}};
  await request('/telegram',body);const count=sent.length;
  await request('/telegram',body);assert.equal(sent.length,count);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,1);
});
test('expired favourites free capacity without requiring delete-all',async()=>{
  await register({start:'2020-01-01',end:'2020-01-02',date_only:true});
  db.prepare('INSERT INTO favourites VALUES(?,?,?)').run('101',eventId,'en');
  await register({id:'b'.repeat(32)});
  await update(101,`/start save_en_${'b'.repeat(32)}`);
  assert.equal(db.prepare('SELECT event_id FROM favourites').get().event_id,'b'.repeat(32));
});
test('oversized body and wrong methods are rejected',async()=>{
  assert.equal((await request('/events',{big:'a'.repeat(66000)})).status,400);
  assert.equal((await worker.fetch(new Request('https://worker.example/events'),env)).status,405);
});
test('an expired callback acknowledgement does not block removal',async()=>{
  await register();await update(101,`/start save_en_${eventId}`);
  globalThis.fetch=async(url)=>Response.json(url.endsWith('answerCallbackQuery') ? {ok:false} : {ok:true,result:{}}, {status:url.endsWith('answerCallbackQuery') ? 400 : 200});
  assert.equal((await callback(101,`remove_en_${eventId}`)).status,200);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM favourites').get().n,0);
});
