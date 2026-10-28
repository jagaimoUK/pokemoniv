"""Check the actual preset UI in Chromium, using synthetic state and no accounts."""
import argparse
import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request
import websocket
from pvpoke_app_ui import HTML

FIXTURE = r'''
metaState={revision:1,default_id:'daily',retrieved:'2026-10-27',items:[
 {id:'daily',name:'いつものメタ',rows:87,default:true,favorite:true},
 {id:'fantasy',name:'ファンタジーカップ',rows:27,favorite:true},
 {id:'great',name:'スーパーリーグ',rows:44,favorite:true},
 {id:'long',name:'非常に長い名前のカスタムプリセットでも見切れずに確認できるメタ',rows:100}
]};selectedMetaId='daily';renderMetaChoices();
const card=el('metaChoose').closest('section');
document.querySelector('header').hidden=true;document.querySelector('nav').hidden=true;
el('login').hidden=true;el('workspace').hidden=false;el('message').hidden=true;
for(const section of document.querySelectorAll('#workspace > .card'))section.hidden=section!==card;
for(const child of card.children)child.hidden=!child.classList.contains('meta-presets')&&child.tagName!=='H2';
card.style.marginTop='0';document.querySelector('main').style.paddingTop='12px';
el('metaQuick').children[1].click();el('metaChoose').click();
setTimeout(()=>{
 const chips=[...document.querySelectorAll('.meta-chip')];
 const controls=[...card.querySelectorAll('.meta-toolbar button,.meta-settings button,.meta-all-row button')];
 document.body.dataset.layout=JSON.stringify({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,
  chips:chips.map(b=>({name:b.textContent,width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height,grow:getComputedStyle(b).flexGrow,selected:b.getAttribute('aria-pressed')})),
  heights:controls.map(b=>b.getBoundingClientRect().height),selected:el('selectedMeta').textContent,
  defaultDisabled:el('metaDefault').disabled,outside:chips.some(b=>b.getBoundingClientRect().right>document.documentElement.clientWidth)});
},100);
'''

def cdp_call(ws, method, params=None):
    cdp_call.sequence += 1
    ident = cdp_call.sequence
    ws.send(json.dumps({'id': ident, 'method': method, 'params': params or {}}))
    while True:
        result = json.loads(ws.recv())
        if result.get('id') == ident:
            if 'error' in result:
                raise RuntimeError(result['error'])
            return result.get('result', {})


cdp_call.sequence = 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('/tmp/meta-controls-qa'))
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    chromium=shutil.which('chromium') or shutil.which('chromium-browser')
    if not chromium:raise SystemExit('Run this inside the existing Docker image (Chromium required)')
    page_html=HTML.replace('<script>','<script>window.fetch=async()=>({status:401,ok:false});',1).replace('</body>','<script>'+FIXTURE+'</script></body>')
    with tempfile.TemporaryDirectory() as d:
        directory=Path(d);page=directory/'presets.html';page.write_text(page_html,encoding='utf-8')
        profile=directory/'chrome';log=(directory/'chromium.log').open('w')
        process=subprocess.Popen([chromium,'--headless','--no-sandbox','--disable-gpu',
            '--disable-dev-shm-usage','--hide-scrollbars','--remote-debugging-port=0',
            '--remote-allow-origins=*','--user-data-dir='+str(profile),'about:blank'],stdout=log,stderr=log)
        ws=None
        try:
            deadline=time.monotonic()+20
            while not (profile/'DevToolsActivePort').exists():
                if time.monotonic()>deadline or process.poll() is not None:
                    raise RuntimeError((directory/'chromium.log').read_text()[-2000:])
                time.sleep(0.1)
            port=(profile/'DevToolsActivePort').read_text().splitlines()[0]
            with urllib.request.urlopen('http://127.0.0.1:'+port+'/json',timeout=10) as response:
                target=next(t for t in json.load(response) if t['type']=='page')
            ws=websocket.create_connection(target['webSocketDebuggerUrl'],timeout=10)
            cdp_call(ws,'Page.enable')
            for width in (320,390,768,1280):
                # Window size alone is clamped to 500px by some Chromium versions.
                cdp_call(ws,'Emulation.setDeviceMetricsOverride',{'width':width,'height':900,
                    'deviceScaleFactor':1,'mobile':width<=560})
                cdp_call(ws,'Page.navigate',{'url':page.as_uri()})
                deadline=time.monotonic()+15
                expression='document.readyState==="complete" && document.body.dataset.layout && JSON.parse(document.body.dataset.layout).width==='+str(width)
                while True:
                    ready=cdp_call(ws,'Runtime.evaluate',{'expression':expression,'returnByValue':True})
                    if ready.get('result',{}).get('value'):break
                    if time.monotonic()>deadline:raise RuntimeError('Layout initialization timed out at '+str(width))
                    time.sleep(0.1)
                m=cdp_call(ws,'Runtime.evaluate',{'expression':'JSON.parse(document.body.dataset.layout)','returnByValue':True})['result']['value']
                screenshot=cdp_call(ws,'Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                (args.output_dir/(str(width)+'.png')).write_bytes(base64.b64decode(screenshot['data']))
                assert m['width']==width,m
                assert m['scrollWidth']<=m['width'] and not m['outside'],m
                assert len(m['chips'])==4 and sum(c['selected']=='true' for c in m['chips'])==1,m
                assert all(c['grow']=='0' and c['height']>=44 for c in m['chips']),m
                assert all(h>=44 for h in m['heights']),m
                assert m['selected']=='ファンタジーカップ' and not m['defaultDisabled'],m
                (args.output_dir/(str(width)+'.json')).write_text(json.dumps(m,ensure_ascii=False,indent=2))
                print(json.dumps(m,ensure_ascii=False))
            # The same real browser also exercises paste -> preview -> explicit save.
            for width in (320,390):
                cdp_call(ws,'Emulation.setDeviceMetricsOverride',{'width':width,'height':1000,
                    'deviceScaleFactor':1,'mobile':True})
                expression = r"""(async()=>{
                    document.querySelector('.meta-presets').closest('section').hidden=true;
                    const manager=el('metaManager');manager.hidden=false;manager.open=true;
                    const csv='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE\n';
                    const input=csv.trim()+',34.5,4,14,13\n'+csv,sha='a'.repeat(64),id='custom:paste-'+WIDTH;
                    window.fetch=async(path,options)=>{
                        const data=JSON.parse(options.body);
                        if(path==='/app-api/meta-preview'){
                            if(data.csv!==input)throw Error('Paste content changed');
                            return {ok:true,status:200,json:async()=>({rows:1,input_rows:2,duplicate_count:1,duplicate_lines:[2],custom_stats_count:1,custom_stats_lines:[1],sha256:sha})};
                        }
                        if(path==='/app-api/meta-preset-save'){
                            if(data.csv!==input||data.expected_sha256!==sha)throw Error('Saved unreviewed content');
                            return {ok:true,status:200,json:async()=>({...metaState,revision:metaState.revision+1,
                                saved_id:id,items:[...metaState.items,{id,name:data.name,rows:1,source:'custom',sha256:sha}]})};
                        }
                        throw Error('Unexpected request '+path);
                    };
                    el('metaName').value='貼り付け確認 '+WIDTH;el('metaText').value=input;
                    el('metaText').dispatchEvent(new Event('input',{bubbles:true}));
                    await el('metaTextPreview').onclick();
                    return {width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,
                        preview:el('metaPreview').textContent,canSave:!el('metaApply').disabled,text:el('metaText').value===input};
                })()""".replace('WIDTH',str(width))
                result=cdp_call(ws,'Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                assert 'exceptionDetails' not in result,result
                pasted=result['result']['value']
                assert pasted['width']==width and pasted['scrollWidth']<=width,pasted
                assert pasted['canSave'] and pasted['text'] and '重複 1行' in pasted['preview'],pasted
                assert 'レベル・個体値付き 1行' in pasted['preview'] and '保存・計算に使いません' in pasted['preview'],pasted
                screenshot=cdp_call(ws,'Page.captureScreenshot',{'format':'png','captureBeyondViewport':False})
                (args.output_dir/(str(width)+'-paste.png')).write_bytes(base64.b64decode(screenshot['data']))
                result=cdp_call(ws,'Runtime.evaluate',{'expression':"(async()=>{await el('metaApply').onclick();return {name:chosenMeta().name,text:el('metaText').value,disabled:el('metaApply').disabled,defaultId:metaState.default_id}})()",'returnByValue':True,'awaitPromise':True})
                assert 'exceptionDetails' not in result,result
                saved=result['result']['value']
                assert saved['name']=='貼り付け確認 '+str(width) and saved['text']=='' and saved['disabled'] and saved['defaultId']=='daily',saved
                expression=r"""(async()=>{
                    const transfer=new DataTransfer();
                    const csv='quagsire,MUD_SHOT,AQUA_TAIL,STONE_EDGE';
                    transfer.items.add(new File([csv+',34.5,4,14,13\r\n'+csv+'\r\n'],'windows-meta.csv',{type:'text/csv'}));
                    el('metaFile').files=transfer.files;await el('metaFile').onchange();
                    return {canSave:!el('metaApply').disabled,hasCR:el('metaText').value.includes('\r'),preview:el('metaPreview').textContent};
                })()"""
                result=cdp_call(ws,'Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                assert 'exceptionDetails' not in result,result
                windows=result['result']['value']
                assert windows['canSave'] and not windows['hasCR'] and '重複 1行' in windows['preview'],windows
                assert 'レベル・個体値付き 1行' in windows['preview'],windows
                print(json.dumps({'paste_preview':pasted,'saved':saved,'windows_file':windows},ensure_ascii=False))
        finally:
            if ws:ws.close()
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            log.close()

if __name__=='__main__':main()
