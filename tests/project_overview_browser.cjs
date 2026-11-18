const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async () => {
  const server = spawn('python', [path.join(__dirname, 'project_overview_preview.py')], {stdio:['ignore','pipe','pipe']});
  let browser;
  try {
    const port = await new Promise((resolve,reject) => {
      let output='';
      const timer=setTimeout(()=>reject(Error('Fixture startup timeout')),30000);
      server.stdout.on('data',part=>{output+=part;const m=output.match(/READY (\d+)/);if(m){clearTimeout(timer);resolve(Number(m[1]));}});
      server.once('exit',code=>{clearTimeout(timer);reject(Error('Fixture exited '+code));});
      server.stderr.on('data',part=>process.stderr.write(part));
    });
    const origin='http://127.0.0.1:'+port;
    browser=await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
    const proof=[];
    for(const width of [390,1280]) {
      const context=await browser.newContext({viewport:{width,height:900}});
      const page=await context.newPage();
      const errors=[],writes=[],external=[];
      page.on('pageerror',error=>errors.push(error.message));
      page.on('request',request=>{if(request.method()!=='GET')writes.push(request.url());if(!request.url().startsWith(origin))external.push(request.url());});
      await page.goto(origin+'/projects');
      assert(await page.getByRole('heading',{name:'Vorgangsübersicht',exact:true}).isVisible());
      const review=page.locator('section.card').filter({has:page.getByRole('link',{name:'Demo Büro',exact:true})});
      assert((await review.innerText()).includes('Neuere Aufnahme noch nicht übernommen'));
      assert((await review.innerText()).includes('1 Position(en) ohne Einbauort'));
      assert((await review.innerText()).includes('Offene Rückfragen: 1'));
      const unknown=page.locator('section.card').filter({has:page.getByRole('link',{name:'Demo unklare Übertragung',exact:true})});
      assert.equal(await unknown.getByRole('link',{name:'Billomat-Status prüfen'}).getAttribute('href'),'/projects/unknown/quote/transfer');
      await review.getByRole('link',{name:'Montageübersicht',exact:true}).click();
      assert(await page.getByRole('heading',{name:'Montageübersicht',exact:true}).isVisible());
      await page.goBack();
      assert(await page.getByRole('heading',{name:'Vorgangsübersicht',exact:true}).isVisible());
      await page.reload();
      await page.getByRole('link',{name:'Demo Lagerhalle',exact:true}).click();
      assert(await page.getByRole('heading',{name:'Demo Lagerhalle',exact:true}).isVisible());
      await page.getByRole('link',{name:'← Projekte',exact:true}).click();
      assert(await page.getByRole('heading',{name:'Vorgangsübersicht',exact:true}).isVisible());
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);
      const folder=process.env.OVERVIEW_ARTIFACTS;
      if(folder){fs.mkdirSync(folder,{recursive:true});await page.screenshot({path:path.join(folder,'overview-'+width+'.png'),fullPage:true});}
      proof.push({width,review_warning:true,missing_room_warning:true,unknown_transfer_reuses_existing:true,back_reload_detail_return:true,no_horizontal_overflow:true,writes,external,js_errors:errors});
      await context.close();
    }
    if(process.env.OVERVIEW_ARTIFACTS)fs.writeFileSync(path.join(process.env.OVERVIEW_ARTIFACTS,'proof.json'),JSON.stringify(proof,null,2));
    console.log(JSON.stringify(proof));
  } finally {
    if(browser)await browser.close();
    server.kill('SIGTERM');
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
