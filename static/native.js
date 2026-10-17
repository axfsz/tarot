// Native app bridge (v0.9.0).
// The iOS and Android apps load this same site inside a Capacitor shell (see mobile/). Inside the
// apps window.Capacitor is present and this file wires the site to native features. In a normal
// browser it only registers the service worker, so the site can be installed as a web app.
(function(){
'use strict';
const cap=window.Capacitor;
const uaApp=(navigator.userAgent.match(/\bOpsTarotApp\/(ios|android)\b/)||[])[1];
const isApp=!!(cap&&(typeof cap.isNativePlatform==='function'?cap.isNativePlatform():uaApp));
const platform=isApp?((typeof cap.getPlatform==='function'&&cap.getPlatform())||uaApp):'web';
// The page is loaded from the server and never imports @capacitor/* packages, so resolve each
// native plugin through whatever the injected bridge offers: Plugins, registerPlugin, or raw calls.
function plugin(name){
 if(typeof cap.isPluginAvailable==='function'&&!cap.isPluginAvailable(name))return undefined;
 if(cap.Plugins&&cap.Plugins[name])return cap.Plugins[name];
 if(typeof cap.registerPlugin==='function'){try{return cap.registerPlugin(name)}catch(e){}}
 if(typeof cap.nativePromise!=='function')return undefined;
 return new Proxy({},{get:(_,method)=>method==='addListener'
  ?(eventName,cb)=>{const id=cap.nativeCallback(name,'addListener',{eventName},cb);return Promise.resolve({remove:()=>cap.nativePromise(name,'removeListener',{callbackId:id,eventName})})}
  :(opts)=>cap.nativePromise(name,method,opts||{})})}
const P={};
if(isApp)for(const n of ['App','Browser','Share','Haptics','LocalNotifications'])P[n]=plugin(n);
const zh=()=>document.documentElement.lang!=='en';
const tt=(a,b)=>zh()?a:b;
const store={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
const OWN_HOSTS=['honeytime.life','www.honeytime.life','tarot.opsglobalonline.com'];
const own=u=>u.origin===location.origin||OWN_HOSTS.includes(u.hostname);
const REMINDER_ID=7001,REMINDER_KEY='ops-reminder';

function tap(style){if(isApp&&P.Haptics)P.Haptics.impact({style:style||'LIGHT'}).catch(()=>{})}
async function share(d){
 if(isApp&&P.Share){try{await P.Share.share({title:d.title,text:d.text,url:d.url,dialogTitle:tt('分享到','Share to')})}catch(e){}return true}
 if(navigator.share){try{await navigator.share(d)}catch(e){}return true}
 return false}
function openExternal(url){if(isApp&&P.Browser)return P.Browser.open({url,presentationStyle:'popover'}).catch(()=>{location.href=url});window.open(url,'_blank','noopener')}

// ---- daily card reminder: a local notification, works offline and needs no push server ----
function reminder(){try{return JSON.parse(store.get(REMINDER_KEY))||{on:false,time:'21:00'}}catch(e){return {on:false,time:'21:00'}}}
async function setReminder(on,time){
 const N=P.LocalNotifications;if(!N)throw Error(tt('当前版本不支持提醒','Reminders are not available in this version'));
 await N.cancel({notifications:[{id:REMINDER_ID}]}).catch(()=>{});
 if(on){
  let perm=await N.checkPermissions();if(perm.display!=='granted')perm=await N.requestPermissions();
  if(perm.display!=='granted')throw Error(tt('请在系统设置里允许本 App 发送通知','Please allow notifications for this app in Settings'));
  const [hour,minute]=time.split(':').map(Number);
  await N.schedule({notifications:[{id:REMINDER_ID,title:tt('今日一牌 ✦','Card of the day ✦'),body:tt('花一分钟，抽一张属于今天的牌。','Take a minute to draw today’s card.'),schedule:{on:{hour,minute},allowWhileIdle:true},extra:{path:'/?daily=1'}}]})}
 store.set(REMINDER_KEY,JSON.stringify({on,time}))}
function reminderPanel(){
 if(!isApp||!P.LocalNotifications)return '';
 const r=reminder();
 return `<section class="panel app-panel" id="app-reminder"><h2>${tt('每日一牌提醒','Daily card reminder')}</h2><p class="muted">${tt('每天在你选的时间提醒你抽一张牌。提醒由手机本地发出，不需要登录。','A gentle daily reminder at the time you choose. It is scheduled on this phone and needs no account.')}</p><form id="reminder-form" class="inline"><label class="switch"><input type="checkbox" name="on" ${r.on?'checked':''}><span>${tt('开启','On')}</span></label><input type="time" name="time" value="${r.time}" aria-label="${tt('提醒时间','Reminder time')}" required><button class="primary">${tt('保存','Save')}</button></form></section>`}
async function offerReminder(){
 // After the first card of the day inside the app, offer the reminder once.
 if(!isApp||!P.LocalNotifications||reminder().on||store.get('ops-reminder-offered'))return;
 store.set('ops-reminder-offered','1');
 if(confirm(tt('要不要每天晚上 9 点提醒你抽一张今日牌？以后可以在“我的”里修改。','Remind you to draw a card every day at 9 pm? You can change this under Account.'))){
  try{await setReminder(true,'21:00');toastLater(tt('已开启每日提醒','Daily reminder is on'))}catch(e){toastLater(e.message)}}}
function toastLater(msg){const e=document.getElementById('toast');if(!e)return alert(msg);e.textContent=msg;e.classList.add('show');setTimeout(()=>e.classList.remove('show'),5000)}

// ---- open ?daily=1 (home-screen shortcut, reminder notification) ----
function openDaily(){
 const q=new URLSearchParams(location.search);if(q.get('daily')!=='1')return;
 history.replaceState(null,'',location.pathname+location.hash);
 let n=0;const iv=setInterval(()=>{const b=document.querySelector('[data-act="daily-card"]');if(b){clearInterval(iv);b.click()}else if(++n>50)clearInterval(iv)},100)}

function goPath(path){if(path&&path!==location.pathname+location.search+location.hash)location.href=path}

function initApp(){
 document.documentElement.classList.add('is-app','is-'+platform);
 // Web Share is missing in WKWebView: route it to the native share sheet.
 if(P.Share){try{Object.defineProperty(navigator,'share',{configurable:true,value:d=>P.Share.share({title:d&&d.title,text:d&&d.text,url:d&&d.url}).then(()=>{})})}catch(e){}}
 // Links to other sites open in an in-app browser sheet instead of replacing the app.
 document.addEventListener('click',e=>{
  const a=e.target.closest&&e.target.closest('a[href]');if(!a||e.defaultPrevented)return;
  let u;try{u=new URL(a.getAttribute('href'),location.href)}catch(err){return}
  if(!/^https?:$/.test(u.protocol)||own(u))return;
  e.preventDefault();openExternal(u.href)},true);
 if(P.App){
  // Universal links / App Links: show the page that was opened inside the app.
  P.App.addListener('appUrlOpen',ev=>{try{const u=new URL(ev.url);if(own(u))goPath(u.pathname+u.search+u.hash)}catch(e){}});
  // Android back button: close the menu, then go back, then leave the app from the home page.
  P.App.addListener('backButton',ev=>{
   if(document.body.classList.contains('menu-open')){document.querySelector('.menu-toggle')?.click();return}
   const home=location.pathname==='/'&&location.hash.length<=1;
   if(ev.canGoBack&&!home)history.back();else P.App.exitApp()})}
 if(P.LocalNotifications){
  P.LocalNotifications.addListener('localNotificationActionPerformed',ev=>{const p=ev.notification&&ev.notification.extra&&ev.notification.extra.path;if(p)goPath(p)})}
 document.addEventListener('submit',async e=>{
  if(e.target.id!=='reminder-form')return;e.preventDefault();
  const f=e.target,b=f.querySelector('button');b.disabled=true;
  try{await setReminder(f.elements.on.checked,f.elements.time.value||'21:00');toastLater(f.elements.on.checked?tt('已开启，每天 '+f.elements.time.value+' 提醒你','Done — you’ll be reminded daily at '+f.elements.time.value):tt('已关闭每日提醒','Daily reminder is off'))}
  catch(err){toastLater(err.message);f.elements.on.checked=false}
  finally{b.disabled=false}},true);
}

if(isApp)initApp();
else if('serviceWorker' in navigator&&location.protocol==='https:')window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));
window.addEventListener('DOMContentLoaded',openDaily);
window.OpsNative={isApp,platform,tap,share,openExternal,reminderPanel,offerReminder};
})();
