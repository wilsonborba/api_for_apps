"""Render docs with external requests blocked. Requires optional Playwright and Chrome."""
import asyncio,json,time,argparse,urllib.parse
from pathlib import Path
from playwright.async_api import async_playwright
parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:18102');parser.add_argument('--chrome',default='/usr/bin/google-chrome');parser.add_argument('--output',type=Path,default=Path('docs/rust-migration'));args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=args.chrome,headless=True,args=['--no-sandbox'])
  page=await browser.new_page();errors=[];blocked=[];responses=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.on('response',lambda r:responses.append({'url':r.url,'status':r.status}))
  async def local_only(route):
   if urllib.parse.urlsplit(route.request.url).netloc == urllib.parse.urlsplit(args.url).netloc or route.request.url.startswith(('data:','blob:')):await route.continue_()
   else:blocked.append(route.request.url);await route.abort()
  await page.route('**/*',local_only)
  t=time.monotonic();await page.goto(args.url.rstrip('/')+'/docs',wait_until='domcontentloaded')
  await page.get_by_text('Asodya Application Gateway API',exact=True).wait_for(timeout=15000)
  await page.wait_for_function("document.querySelector('#docs-reference').innerText.includes('/user/sync/v1/oauth/callback')")
  elapsed=time.monotonic()-t
  await page.wait_for_function("document.querySelectorAll('.scalar-api-reference').length === 1 && !document.querySelector('.introduction-loading')")
  box=await page.get_by_text('Asodya Application Gateway API',exact=True).bounding_box()
  assert box and 0 <= box['y'] < page.viewport_size['height'], box
  await page.screenshot(path=str(args.output/'docs-1.2.1-browser.png'),full_page=False)
  result={'rendered':True,'scalar_instances':await page.locator('.scalar-api-reference').count(),'seconds_to_routes':elapsed,'errors':errors,'external_attempts':blocked,'responses':responses,'version_visible':await page.get_by_text('v1.2.1',exact=True).count(),'font_family':await page.locator('body').evaluate('(el)=>getComputedStyle(el).fontFamily')}
  # A failed schema request must show a readable message instead of an empty page.
  await page.route('**/openapi.json',lambda route:route.fulfill(status=503,body='unavailable'))
  await page.reload(wait_until='domcontentloaded')
  await page.get_by_role('status').filter(has_text='Documentation could not load').wait_for(timeout=10000)
  result['schema_failure_message']=True
  (args.output/'docs-1.2.1-browser.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));assert not errors
  await browser.close()
asyncio.run(main())
