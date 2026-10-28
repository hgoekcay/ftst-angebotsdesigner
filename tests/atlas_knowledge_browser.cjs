// Optional real-browser regression: node tests/atlas_knowledge_browser.cjs
// Requires Playwright and its Chromium. All data and APIs below are synthetic.
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1280,height:900},colorScheme:'light'});
 const page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 let memories=[{id:1,text:'Kunde Muster: Wartung im November.',source:'Besprechung',tags:['Kunde Muster','Wartung'],revision:1,created_at:'2026-10-29T08:00:00Z',updated_at:'2026-10-29T08:00:00Z'}],revisions=[structuredClone(memories[0])],tasks=[],forceConflict=false;
 const mutations=[];
 await page.route('http://atlas.test/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method();
  if(!path.startsWith('/api/')){const file=path==='/'?'index.html':path.slice(1);return route.fulfill({contentType:file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync('ftst_atlas/'+file)});}
  let result={},status=200;const body=req.postDataJSON();
  if(method!=='GET')mutations.push({path,method,body,csrf:req.headers()['x-atlas-csrf']});
  if(path==='/api/status')result={csrf_token:'test-csrf',version:'test',online:{reason:'nicht eingerichtet'}};
  else if(path==='/api/profile')result={text:'Synthetischer Testbetrieb'};
  else if(path==='/api/jobs')result={jobs:[]};
  else if(path==='/api/memories'&&method==='GET')result={memories:memories.filter(m=>!url.searchParams.get('q')||JSON.stringify(m).toLowerCase().includes(url.searchParams.get('q').toLowerCase()))};
  else if(path==='/api/memories/1/revisions')result={revisions};
  else if(path==='/api/memories/1'&&method==='PATCH'){
   if(forceConflict){status=409;result={error:'Wissen wurde inzwischen geändert. Bitte neu laden.'};}
   else {assert.equal(body.revision,memories[0].revision);memories[0]={...memories[0],...body,revision:body.revision+1,updated_at:'2026-10-29T09:00:00Z'};revisions.unshift(structuredClone(memories[0]));result={memory:memories[0]};}
  } else if(path==='/api/tasks'&&method==='POST'){tasks.push({id:1,...body,done:false});result={task:tasks[0]};}
  else if(path==='/api/tasks')result={tasks};
  else {status=404;result={error:'Unexpected route '+path};}
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(result)});
 });
 await page.goto('http://atlas.test/');
 await page.locator('[data-view=knowledge]').click();
 await page.getByText('Kunde Muster: Wartung im November.',{exact:true}).waitFor();
 await page.locator('#memory-search').fill('nicht vorhanden');
 await page.locator('#memory-search-form').getByRole('button',{name:'Suchen',exact:true}).click();
 await page.getByText('Keine passenden Einträge. Versuche einen anderen Suchbegriff.').waitFor();
 await page.locator('#memory-search-reset').click();
 await page.getByRole('button',{name:'Korrigieren',exact:true}).click();
 await page.locator('#memory-text').fill('Kunde Muster: Wartung im Dezember. <img src=x onerror=alert(1)>');
 await page.locator('#memory-tags').fill('Kunde Muster, Wartung, Dezember');
 await page.locator('#memory-save').click();
 await page.getByText('Korrektur gespeichert. Frühere Fassungen stehen im Verlauf.',{exact:true}).waitFor();
 assert.equal(await page.locator('#memory-list img').count(),0,'untrusted text is not HTML');
 assert.equal(memories[0].revision,2);assert.deepEqual(memories[0].tags,['Kunde Muster','Wartung','Dezember']);
 await page.locator('.memory-history summary').click();
 await page.locator('.memory-history').getByText('Kunde Muster: Wartung im November.',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Korrigieren',exact:true}).click();
 forceConflict=true;
 await page.locator('#memory-text').fill('Nicht verlieren');await page.locator('#memory-save').click();
 await page.getByText('Wissen wurde inzwischen geändert. Bitte neu laden.',{exact:true}).waitFor();
 assert.equal(await page.locator('#memory-text').inputValue(),'Nicht verlieren','conflict preserves edit');
 forceConflict=false;await page.locator('#memory-cancel').click();
 await page.getByRole('button',{name:'Aufgabe dazu',exact:true}).click();
 await page.locator('#task-title').fill('Wartung vorbereiten');await page.locator('#task-form').getByRole('button').click();
 await page.getByText('Wartung vorbereiten',{exact:true}).waitFor();
 assert.deepEqual(tasks[0].knowledge_ids,[1]);
 await page.locator('.task-linked-knowledge summary').click();
 await page.locator('.task-linked-knowledge').getByText(memories[0].text,{exact:true}).waitFor();
 await page.locator('[data-view=knowledge]').click();
 await page.locator('.memory-card').waitFor();
 await page.screenshot({path:'/tmp/atlas-knowledge-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.emulateMedia({colorScheme:'dark'});
 await page.screenshot({path:'/tmp/atlas-knowledge-mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'mobile has no horizontal overflow');
 assert.deepEqual(errors,[]);
 assert(mutations.every(m=>m.csrf==='test-csrf'),'writes carry CSRF');
 console.log('Knowledge browser checks passed: search, tags, revision correction/history, stale-edit retention, escaped content, task linkage, CSRF, mobile overflow.');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
