const ID = /^[a-f0-9]{32}$/;
const LANG = /^(en|ru)$/;
const MAX_FAVOURITES = 100;
const PAGE_SIZE = 5;
const words = {
  en: {saved: 'Saved ⭐', missing: 'This event is unavailable or has already ended.',
    full: 'Your list is full (100 events). Remove an event first.', list: '⭐ My events',
    empty: 'You have no saved upcoming events.', remove: 'Remove', open: 'Open event',
    removed: 'Removed from your favourites.', next: 'Next →', previous: '← Previous',
    cancelled: '❌ Cancelled', deleted: 'Your saved events have been deleted.',
    intro: 'Save events using the ⭐ button in the channel. Your favourites are private. Use /events to see your upcoming events, /privacy for details or /delete_me to clear your list.',
    privacy: 'We store your Telegram user ID, saved event IDs and selected language in a private Cloudflare database. We do not store your name or message history. /delete_me removes all your saved entries. This list is separate from Telegram Saved Messages.',
    confirm: 'Delete all your saved events?', yes: 'Delete all', no: 'Keep them'},
  ru: {saved: 'Сохранено ⭐', missing: 'Событие недоступно или уже закончилось.',
    full: 'В списке уже 100 событий. Сначала удалите одно из них.', list: '⭐ Мои события',
    empty: 'Нет сохранённых предстоящих событий.', remove: 'Удалить', open: 'Подробнее',
    removed: 'Удалено из избранного.', next: 'Далее →', previous: '← Назад',
    cancelled: '❌ Отменено', deleted: 'Все ваши сохранённые события удалены.',
    intro: 'Сохраняйте события кнопкой ⭐ в канале. Ваш список виден только вам. /events — предстоящие события, /privacy — хранение данных, /delete_me — очистить список.',
    privacy: 'В закрытой базе Cloudflare хранятся ваш Telegram ID, ID сохранённых событий и выбранный язык. Имя и история сообщений не сохраняются. /delete_me удаляет все ваши записи. Этот список не связан с «Избранным» Telegram.',
    confirm: 'Удалить все сохранённые события?', yes: 'Удалить все', no: 'Оставить'}
};
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const short = (value, length) => [...String(value)].slice(0, length).join('');
function safeUrl(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password; }
  catch { return false; }
}
function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/.test(value)
    && Number.isFinite(Date.parse(value));
}
export function validEvent(e) {
  return e && typeof e.id === 'string' && ID.test(e.id) && typeof e.language === 'string' && LANG.test(e.language) && typeof e.url === 'string' && e.url.length <= 2000 && safeUrl(e.url)
    && [['title',200], ['summary',500], ['venue',200], ['municipality',100]].every(([key, max]) => typeof e[key] === 'string' && [...e[key]].length <= max)
    && e.title.trim() && validDate(e.start) && validDate(e.end) && Date.parse(e.end) >= Date.parse(e.start)
    && typeof e.date_only === 'boolean' && typeof e.cancelled === 'boolean'
    && Array.isArray(e.dates)
    && e.dates.every(d => validDate(d.start) && validDate(d.end) && Date.parse(d.end) >= Date.parse(d.start));
}
export function nextOccurrence(event, now = new Date()) {
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Helsinki', year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
  const dates = typeof event.dates === 'string' ? JSON.parse(event.dates) : event.dates;
  return (dates.length ? dates : [{start:event.start,end:event.end}])
    .filter(d => event.date_only ? d.end.slice(0,10) >= today : Date.parse(d.end) >= now.getTime())
    .sort((a,b) => Date.parse(a.start) - Date.parse(b.start))[0] || null;
}
function dateLabel(event, occurrence, language) {
  const format = new Intl.DateTimeFormat(language === 'ru' ? 'ru-RU' : 'en-GB', {
    timeZone:'Europe/Helsinki', day:'numeric', month:'short', year:'numeric',
    ...(event.date_only ? {} : {hour:'2-digit', minute:'2-digit'})});
  if (event.date_only) return `${occurrence.start.slice(0,10)}–${occurrence.end.slice(0,10)}`;
  return format.format(new Date(occurrence.start));
}
async function telegram(env, method, payload) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload), signal:AbortSignal.timeout(10000)});
  const result = await response.json();
  // A blocked bot cannot reply; retrying the same update will never help.
  if (response.status === 403) return null;
  // Telegram's short-lived callback acknowledgement can expire while an update
  // is being retried. Still apply the user's idempotent action and reply privately.
  if (method === 'answerCallbackQuery' && response.status === 400) return null;
  if (!response.ok || !result.ok) throw new Error('Telegram request failed');
  return result.result;
}
const listButton = language => ({text:words[language].list, callback_data:`list_${language}_0`});
async function send(env, user, text, buttons = []) {
  return telegram(env,'sendMessage', {chat_id:user, text, parse_mode:'HTML',
    link_preview_options:{is_disabled:true}, reply_markup:{inline_keyboard:buttons}});
}
async function pruneExpired(env, user) {
  const {results}=await env.DB.prepare('SELECT e.* FROM favourites f JOIN events e ON e.id=f.event_id WHERE f.user_id=?').bind(user).all();
  const expired=results.filter(e=>!nextOccurrence(e));
  if(expired.length) await env.DB.batch(expired.map(e=>env.DB.prepare('DELETE FROM favourites WHERE user_id=? AND event_id=?').bind(user,e.id)));
}
export async function cleanupOldFavourites(env, now = new Date()) {
  const cutoff = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  const day = new Intl.DateTimeFormat('en-CA', {
    timeZone:'Europe/Helsinki', year:'numeric', month:'2-digit', day:'2-digit'
  }).format(cutoff);
  // Only delete once every occurrence has ended more than a week ago.
  // Keep the public catalogue intact, so other users and recurring dates work.
  await env.DB.prepare(`DELETE FROM favourites WHERE event_id IN (
    SELECT e.id FROM events e JOIN (SELECT DISTINCT event_id FROM favourites) f ON f.event_id=e.id
    WHERE NOT EXISTS (
      SELECT 1 FROM json_each(CASE WHEN json_array_length(e.dates)>0 THEN e.dates
        ELSE json_array(json_object('end',e.end)) END) occurrence
      WHERE CASE WHEN e.date_only=1
        THEN substr(json_extract(occurrence.value,'$.end'),1,10)>=?
        ELSE julianday(json_extract(occurrence.value,'$.end'))>=julianday(?) END
    )
  )`).bind(day,cutoff.toISOString()).run();
}
async function save(env, user, id, language) {
  const event = await env.DB.prepare('SELECT e.*, t.title FROM events e JOIN event_texts t ON t.event_id=e.id WHERE e.id=? AND t.language=?').bind(id,language).first();
  if (!event || event.cancelled || !nextOccurrence(event)) return send(env,user,words[language].missing, [[listButton(language)]]);
  await pruneExpired(env,user);
  await env.DB.prepare(`INSERT INTO favourites(user_id,event_id,language)
    SELECT ?,?,? WHERE (SELECT COUNT(*) FROM favourites WHERE user_id=?) < ?
      OR EXISTS(SELECT 1 FROM favourites WHERE user_id=? AND event_id=?)
    ON CONFLICT(user_id,event_id) DO UPDATE SET language=excluded.language`)
    .bind(user,id,language,user,MAX_FAVOURITES,user,id).run();
  const saved = await env.DB.prepare('SELECT event_id FROM favourites WHERE user_id=? AND event_id=?').bind(user,id).first();
  if (!saved) return send(env,user,words[language].full, [[listButton(language)]]);
  return send(env,user,`${words[language].saved}\n<b>${escape(event.title)}</b>\n${escape(dateLabel(event,nextOccurrence(event),language))}`,
    [[{text:words[language].open,url:event.url}], [listButton(language), {text:words[language].remove,callback_data:`remove_${language}_${id}`}]]);
}
async function list(env, user, language, page = 0) {
  await pruneExpired(env,user);
  const {results} = await env.DB.prepare(`SELECT e.*, COALESCE(t.title, saved.title) AS title,
    COALESCE(t.summary, saved.summary) AS summary FROM favourites f JOIN events e ON e.id=f.event_id
    LEFT JOIN event_texts t ON t.event_id=e.id AND t.language=?
    JOIN event_texts saved ON saved.event_id=e.id AND saved.language=f.language WHERE f.user_id=?`).bind(language,user).all();
  const events = results.map(e => ({...e, occurrence:nextOccurrence(e)})).filter(e => e.occurrence)
    .sort((a,b) => Date.parse(a.occurrence.start)-Date.parse(b.occurrence.start) || a.id.localeCompare(b.id));
  if (!events.length) return send(env,user,words[language].empty);
  page = Math.min(page, Math.floor((events.length - 1)/PAGE_SIZE));
  const visible = events.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  const lines = [`<b>${words[language].list}</b> · ${page+1}/${Math.ceil(events.length/PAGE_SIZE)}`];
  const buttons = [];
  visible.forEach((event,index) => {
    const n = page*PAGE_SIZE+index+1;
    lines.push(`${n}. <b>${escape(short(event.title,100))}</b>${event.cancelled ? '\n'+words[language].cancelled : ''}\n${escape(dateLabel(event,event.occurrence,language))}\n${escape(short([event.venue,event.municipality].filter(Boolean).join(', '),100))}\n${escape(short(event.summary,100))}`);
    buttons.push([{text:`${n}. ${words[language].open}`,url:event.url}, {text:`${n}. ${words[language].remove}`,callback_data:`remove_${language}_${event.id}`}]);
  });
  const nav=[];
  if (page>0) nav.push({text:words[language].previous,callback_data:`list_${language}_${page-1}`});
  if ((page+1)*PAGE_SIZE<events.length) nav.push({text:words[language].next,callback_data:`list_${language}_${page+1}`});
  if (nav.length) buttons.push(nav);
  return send(env,user,lines.join('\n\n'),buttons);
}
export async function handleUpdate(update, env) {
  const callback = update.callback_query;
  const message = callback?.message || update.message;
  const from = callback?.from || message?.from;
  if (!message || !from || from.is_bot || !Number.isSafeInteger(from.id) || from.id<=0
    || message.chat?.type!=='private' || message.chat.id!==from.id) return;
  const user=String(from.id), language=from.language_code?.startsWith('ru') ? 'ru' : 'en';
  if (callback) {
    // Acknowledge promptly, never change the shared channel button for one user.
    await telegram(env,'answerCallbackQuery',{callback_query_id:callback.id});
    let match=/^list_(en|ru)_([0-9]{1,2})$/.exec(callback.data);
    if (match) return list(env,user,match[1],Number(match[2]));
    match=/^remove_(en|ru)_([a-f0-9]{32})$/.exec(callback.data);
    if (match) {
      await env.DB.prepare('DELETE FROM favourites WHERE user_id=? AND event_id=?').bind(user,match[2]).run();
      return send(env,user,words[match[1]].removed,[[listButton(match[1])]]);
    }
    match=/^delete_(en|ru)$/.exec(callback.data);
    if (match) {
      await env.DB.prepare('DELETE FROM favourites WHERE user_id=?').bind(user).run();
      return send(env,user,words[match[1]].deleted);
    }
    return;
  }
  const text=message.text || '';
  const saved=/^\/start(?:@\w+)? save_(en|ru)_([a-f0-9]{32})$/.exec(text);
  if (saved) return save(env,user,saved[2],saved[1]);
  const command=/^\/(start|events|help|privacy|delete_me)(?:@\w+)?(?:\s|$)/.exec(text)?.[1];
  if (command==='events') return list(env,user,language);
  if (command==='privacy') return send(env,user,words[language].privacy);
  if (command==='delete_me') return send(env,user,words[language].confirm,
    [[{text:words[language].yes,callback_data:`delete_${language}`},listButton(language)]]);
  return send(env,user,words[language].intro,[[listButton(language)]]);
}
async function readJson(request, maxBytes) {
  const reader=request.body?.getReader();
  if (!reader) throw new Error('Bad body');
  const chunks=[]; let size=0;
  while (true) {
    const {done,value}=await reader.read(); if (done) break;
    size+=value.length; if(size>maxBytes) {await reader.cancel();throw new Error('Bad body');}
    chunks.push(value);
  }
  const bytes=new Uint8Array(size);let offset=0;
  for(const chunk of chunks) {bytes.set(chunk,offset);offset+=chunk.length;}
  return JSON.parse(new TextDecoder().decode(bytes));
}
export default {
  async scheduled(controller, env) {
    await cleanupOldFavourites(env, new Date(controller.scheduledTime));
  },
  async fetch(request, env) {
    const path=new URL(request.url).pathname;
    if(path==='/health' && request.method==='GET') {
      if(!env.DB || !env.FAVOURITES_SYNC_SECRET || !env.TELEGRAM_WEBHOOK_SECRET || !env.TELEGRAM_BOT_TOKEN) return new Response('Not configured',{status:503});
      try {await env.DB.prepare('SELECT id FROM events LIMIT 1').first();return Response.json({ok:true});}
      catch {return new Response('Not ready',{status:503});}
    }
    if(!['/events','/telegram'].includes(path)) return new Response('Not found',{status:404});
    if(request.method!=='POST') return new Response('Method not allowed',{status:405});
    const secret=path==='/events' ? env.FAVOURITES_SYNC_SECRET : env.TELEGRAM_WEBHOOK_SECRET;
    const supplied=path==='/events' ? request.headers.get('Authorization') : request.headers.get('X-Telegram-Bot-Api-Secret-Token');
    if(!secret || !env.DB || !env.TELEGRAM_BOT_TOKEN) return new Response('Not configured',{status:503});
    if(supplied!==(path==='/events' ? `Bearer ${secret}` : secret)) return new Response('Unauthorized',{status:401});
    let body;
    // Public catalogue schedules can span years; Telegram updates stay small.
    try {body=await readJson(request, path==='/events' ? 1048576 : 65536);} catch {return new Response('Invalid JSON',{status:400});}
    try {
      if(path==='/events') {
        if(!validEvent(body)) return new Response('Invalid event',{status:400});
        await env.DB.batch([
          env.DB.prepare(`INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            url=excluded.url,venue=excluded.venue,municipality=excluded.municipality,start=excluded.start,
            end=excluded.end,dates=excluded.dates,date_only=excluded.date_only,cancelled=excluded.cancelled`)
            .bind(body.id,body.url,body.venue,body.municipality,body.start,body.end,JSON.stringify(body.dates),Number(body.date_only),Number(body.cancelled)),
          env.DB.prepare(`INSERT INTO event_texts VALUES(?,?,?,?) ON CONFLICT(event_id,language) DO UPDATE SET title=excluded.title,summary=excluded.summary`)
            .bind(body.id,body.language,body.title,body.summary)
        ]);
      } else {
        if(!Number.isSafeInteger(body?.update_id) || body.update_id<0) return new Response('Invalid update',{status:400});
        if(await env.DB.prepare('SELECT update_id FROM processed_updates WHERE update_id=?').bind(body.update_id).first()) return Response.json({ok:true});
        await handleUpdate(body,env);
        await env.DB.batch([
          env.DB.prepare('INSERT OR IGNORE INTO processed_updates(update_id) VALUES(?)').bind(body.update_id),
          env.DB.prepare("DELETE FROM processed_updates WHERE completed_at < datetime('now','-7 days')")
        ]);
      }
      return Response.json({ok:true});
    } catch {
      // Never log incoming Telegram payloads, IDs or credential-bearing URLs.
      console.error('Favourites request failed');
      return new Response('Retry later',{status:503});
    }
  }
};
