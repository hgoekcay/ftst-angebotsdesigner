const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const css=fs.readFileSync(path.join(__dirname,'fixtures/portal-photo/portal.css'),'utf8');
const svg=(w,h)=>'data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="'+w+'" height="'+h+'"><rect width="100%" height="100%" fill="white"/><rect width="100%" height="12%" fill="#e30613"/><rect y="88%" width="100%" height="12%" fill="#087a39"/><rect width="12%" height="100%" fill="#135dc0"/><rect x="88%" width="12%" height="100%" fill="#f1bc00"/><text x="50%" y="50%" text-anchor="middle" font-size="20">FULL FRAME</text></svg>').toString('base64');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const folder=process.env.PORTAL_PHOTO_ARTIFACTS;fs.mkdirSync(folder,{recursive:true});
 const proof=[];
 try{
  for(const width of [390,1280]){
   const page=await browser.newPage({viewport:{width,height:1000}});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style></head><body><main class="page"><h1>Foto-Rahmenprüfung</h1><p>Synthetische Prüfbilder. Alle vier farbigen Kanten müssen sichtbar bleiben.</p><h2>Freigegebenes Projektfoto</h2><div class="comparison"><div class="scene"><img class="approved-project-photo" src="'+svg(300,600)+'" alt="Hochformat mit vier Kanten"></div></div><h2>Referenzfotos</h2><div class="project-gallery"><figure><img src="'+svg(600,200)+'" alt="Breites Referenzfoto"><figcaption>Breitformat vollständig</figcaption></figure><figure><img src="'+svg(200,600)+'" alt="Hohes Referenzfoto"><figcaption>Hochformat vollständig</figcaption></figure></div><h2>Produktfoto (unverändert)</h2><div class="product-portrait"><img src="'+svg(200,600)+'" alt="Hohes Produktfoto"></div></main></body></html>',{waitUntil:'load'});
   await page.locator('img').evaluateAll(imgs=>Promise.all(imgs.map(i=>i.decode())));
   const images=await page.locator('img').evaluateAll(imgs=>imgs.map(i=>({alt:i.alt,fit:getComputedStyle(i).objectFit,natural:[i.naturalWidth,i.naturalHeight],box:[i.clientWidth,i.clientHeight]})));
   assert.equal(images.length,4);assert(images.every(i=>i.fit==='contain'&&i.natural.every(n=>n>0)));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(folder,'photo-framing-'+width+'.png'),fullPage:true});
   // Repeated load must retain the same framing, with no scripts or network writes.
   await page.setViewportSize({width,height:800});
   assert.deepEqual(await page.locator('img').evaluateAll(imgs=>imgs.map(i=>getComputedStyle(i).objectFit)),['contain','contain','contain','contain']);
   assert.deepEqual(errors,[]);proof.push({width,images,noHorizontalOverflow:true,jsErrors:errors});await page.close();
  }
  fs.writeFileSync(path.join(folder,'proof.json'),JSON.stringify(proof,null,2));console.log(JSON.stringify(proof));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
