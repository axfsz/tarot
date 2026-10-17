// Ops Tarot Studio service worker (v0.9.0). Served at /sw.js with the asset version baked in.
// Pages always come from the network (readings and accounts are live data); the worker only
// keeps versioned assets and card artwork for speed, and shows /offline when there is no network.
const VERSION='__VERSION__';
const CACHE='ops-static-'+VERSION, CARDS='ops-cards-v1', OFFLINE='/offline';
const PRECACHE=[OFFLINE,'/static/offline.css','/static/favicon.svg','/static/icon-192.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(PRECACHE)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('ops-static-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
async function cacheFirst(cacheName,req){
 const cache=await caches.open(cacheName);const hit=await cache.match(req);if(hit)return hit;
 const res=await fetch(req);if(res.ok&&res.type==='basic')cache.put(req,res.clone());return res}
self.addEventListener('fetch',e=>{
 const req=e.request;if(req.method!=='GET')return;
 const url=new URL(req.url);if(url.origin!==self.location.origin)return;
 const p=url.pathname;if(p.startsWith('/api/')||p.startsWith('/admin')||p==='/setup'||p==='/sw.js')return;
 if(req.mode==='navigate'){e.respondWith(fetch(req).catch(()=>caches.match(OFFLINE)));return}
 if(p.startsWith('/static/tarot/')){e.respondWith(cacheFirst(CARDS,req));return}
 if(p.startsWith('/static/')&&url.searchParams.has('v')){e.respondWith(cacheFirst(CACHE,req));return}
});
