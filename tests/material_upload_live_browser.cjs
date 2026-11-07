const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const {chromium} = require('playwright');
(async () => {
  const server = spawn('python', [path.join(__dirname, 'material_upload_preview.py')], {stdio:['ignore','pipe','pipe']});
  let browser;
  try {
    const port = await new Promise((resolve,reject) => {
      let output='';
      const timer=setTimeout(()=>reject(Error('Photo fixture startup timeout')),45000);
      server.stdout.on('data',part=>{output+=part;const m=output.match(/READY (\d+)/);if(m){clearTimeout(timer);resolve(Number(m[1]));}});
      server.on('exit',code=>{clearTimeout(timer);reject(Error('Photo fixture exited '+code));});
      server.stderr.on('data',part=>process.stderr.write(part));
    });
    const origin='http://127.0.0.1:'+port;
    const png=Buffer.from(await (await fetch(origin+'/qa/fixture.png')).arrayBuffer());
    browser=await chromium.launch({headless:true});
    const proof=[];
    for(const width of [390,1280]) {
      const context=await browser.newContext({viewport:{width,height:900}});
      const page=await context.newPage();
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.goto(origin+'/materials');
      await page.locator('#photo-files').setInputFiles([
        {name:'A-'+width+'.png',mimeType:'image/png',buffer:png},
        {name:'B-'+width+'.png',mimeType:'image/png',buffer:png}
      ]);
      const first=page.locator('#photo-0-description'),second=page.locator('#photo-1-description');
      await first.fill('Eigene Beschreibung A '+width);
      await second.fill('Eigene Beschreibung B '+width);
      await page.locator('#photo-0-category').selectOption('Alarmanlage');
      await page.locator('#photo-1-category').selectOption('Videoüberwachung');
      await page.locator('#photo-batch button').click();
      await page.waitForFunction(()=>JSON.parse(sessionStorage.getItem('ftst-photo-batch:/materials/batch')).rows.every(r=>r.uploaded));
      assert(await first.isEnabled());assert(await second.isEnabled());
      await first.evaluate(el=>{el.dataset.identity='retained';});
      const token=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('ftst-photo-batch:/materials/batch')).rows[0].token);
      await page.request.post(origin+'/qa/suggest',{data:{token}});
      await page.waitForFunction(()=>JSON.parse(sessionStorage.getItem('ftst-photo-batch:/materials/batch')).rows[0].status==='ready');
      assert.equal(await first.inputValue(),'Eigene Beschreibung A '+width);
      assert.equal(await second.inputValue(),'Eigene Beschreibung B '+width);
      assert.equal(await first.getAttribute('data-identity'),'retained');
      const description2='Zweite Beschreibung weiter bearbeitet '+width;
      await second.fill(description2);
      const sent=page.waitForRequest(r=>r.url().endsWith('/materials/batch/commit')&&r.method()==='POST');
      await page.locator('#photo-commit').click();
      const body=(await sent).postDataJSON();
      assert.equal(body.items.length,2);
      assert.equal(body.items[1].manual,true);
      assert.equal(body.items[0].description,'Eigene Beschreibung A '+width);
      assert.equal(body.items[1].description,description2);
      await page.waitForFunction(()=>JSON.parse(sessionStorage.getItem('ftst-photo-batch:/materials/batch')).rows.every(r=>r.status==='committed'));
      await page.goto(origin+'/materials');
      const edit=page.locator('.material-tile a[href$="/edit"]').filter({hasText:'Beschreibung'}).first();
      const target=await edit.getAttribute('href');
      const file=target.replace(/\/edit$/,'');
      const before=Buffer.from(await (await page.request.get(origin+file)).body());
      await edit.click();
      await page.locator('#description').fill('Nachträglich geändert '+width);
      await page.getByRole('button',{name:'Bildangaben speichern'}).click();
      assert((await page.locator('.material-tile').allTextContents()).some(s=>s.includes('Nachträglich geändert '+width)));
      const after=Buffer.from(await (await page.request.get(origin+file)).body());
      assert.deepEqual(before,after,'Editing descriptions must preserve image bytes');
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      assert.deepEqual(errors,[]);
      const folder=process.env.PHOTO_ARTIFACTS;
      if(folder){fs.mkdirSync(folder,{recursive:true});await page.screenshot({path:path.join(folder,'photo-library-'+width+'.png'),fullPage:true});}
      proof.push({width,independent_descriptions:true,manual_save_while_other_queued:true,late_ai_preserves_text_and_dom:true,saved_description_edit:true,image_bytes_unchanged:true,js_errors:errors});
      await context.close();
    }
    const folder=process.env.PHOTO_ARTIFACTS;
    if(folder)fs.writeFileSync(path.join(folder,'proof.json'),JSON.stringify(proof,null,2));
    console.log(JSON.stringify(proof));
  } finally {
    if(browser)await browser.close();
    server.kill('SIGTERM');
    await new Promise(resolve=>{if(server.exitCode!==null)resolve();else{server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},5000).unref();}});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
