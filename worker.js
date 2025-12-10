export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 1. 图片代理
    if (url.pathname.startsWith('/image/')) {
      const fileId = url.pathname.split('/')[2];
      return proxyTelegramImage(fileId, env.BOT_TOKEN);
    }

    // 2. API (搜索/列表)
    if (url.pathname === '/api/posts') {
      const q = url.searchParams.get('q');
      const offset = url.searchParams.get('offset') || 0;
      let sql = q 
        ? `SELECT * FROM posts WHERE title LIKE ? OR author LIKE ? OR tags LIKE ? ORDER BY timestamp DESC LIMIT 20 OFFSET ?`
        : `SELECT * FROM posts ORDER BY timestamp DESC LIMIT 20 OFFSET ?`;
      const params = q ? [`%${q}%`, `%${q}%`, `%${q}%`, offset] : [offset];
      
      const { results } = await env.DB.prepare(sql).bind(...params).all();
      return new Response(JSON.stringify(results), { headers: { 'Content-Type': 'application/json' }});
    }

    // 3. 前端 HTML
    return new Response(htmlTemplate(), { headers: { 'Content-Type': 'text/html;charset=UTF-8' }});
  }
};

async function proxyTelegramImage(fileId, botToken) {
  try {
    const r1 = await fetch(`https://api.telegram.org/bot${botToken}/getFile?file_id=${fileId}`);
    const j1 = await r1.json();
    if (!j1.ok) return new Response('TG Error', { status: 502 });
    const r2 = await fetch(`https://api.telegram.org/file/bot${botToken}/${j1.result.file_path}`);
    const h = new Headers(r2.headers);
    h.set('Cache-Control', 'public, max-age=31536000'); // 缓存1年
    return new Response(r2.body, { headers: h });
  } catch (e) { return new Response('Proxy Error', { status: 500 }); }
}

function htmlTemplate() {
  return `
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gallery</title>
<style>
body{background:#121212;color:#eee;margin:0;font-family:sans-serif}
.search{position:sticky;top:0;background:#121212;padding:15px;text-align:center;z-index:9}
input{background:#333;border:none;padding:12px;border-radius:20px;width:80%;color:#fff}
.grid{column-count:2;gap:10px;padding:10px}
@media(min-width:768px){.grid{column-count:4}}
.card{break-inside:avoid;background:#1e1e1e;margin-bottom:10px;border-radius:8px;overflow:hidden}
img{width:100%;display:block;min-height:150px;background:#222}
.meta{padding:8px}
.title{font-size:13px;font-weight:bold;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.author{font-size:12px;color:#888}
</style>
</head>
<body>
<div class="search"><input type="text" placeholder="Search..." onchange="search(this.value)"></div>
<div class="grid" id="g"></div>
<script>
let off=0,q='',loading=false;
async function load(reset=false){
  if(loading)return;loading=true;
  if(reset){document.getElementById('g').innerHTML='';off=0;}
  let res=await fetch(\`/api/posts?q=\${encodeURIComponent(q)}&offset=\${off}\`);
  let data=await res.json();
  let html=data.map(p=>{
    let imgs=JSON.parse(p.images);
    return \`<div class="card"><img src="/image/\${imgs[0]}" loading="lazy"><div class="meta"><div class="title">\${p.title}</div><div class="author">\${p.author}</div></div></div>\`
  }).join('');
  document.getElementById('g').insertAdjacentHTML('beforeend',html);
  off+=20;loading=false;
}
function search(val){q=val;load(true);}
window.onscroll=()=>{if(window.innerHeight+scrollY>=document.body.offsetHeight-500)load()};
load();
</script></body></html>`;
}
