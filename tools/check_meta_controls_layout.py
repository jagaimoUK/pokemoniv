"""Check the actual preset UI in Chromium, using synthetic state and no accounts."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
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
card.style.marginTop='0';document.querySelector('main').style.padding='12px';
el('metaQuick').children[1].click();el('metaChoose').click();
setTimeout(()=>{
 const chips=[...document.querySelectorAll('.meta-chip')];
 const controls=[...document.querySelectorAll('.meta-toolbar button,.meta-settings button,.meta-all-row button')];
 document.body.dataset.layout=JSON.stringify({width:document.documentElement.clientWidth,scrollWidth:document.documentElement.scrollWidth,
  chips:chips.map(b=>({name:b.textContent,width:b.getBoundingClientRect().width,height:b.getBoundingClientRect().height,grow:getComputedStyle(b).flexGrow,selected:b.getAttribute('aria-pressed')})),
  heights:controls.map(b=>b.getBoundingClientRect().height),selected:el('selectedMeta').textContent,
  defaultDisabled:el('metaDefault').disabled,outside:chips.some(b=>b.getBoundingClientRect().right>document.documentElement.clientWidth)});
},100);
'''

class MetricsParser(HTMLParser):
    result = None
    def handle_starttag(self, tag, attrs):
        if tag == 'body' and dict(attrs).get('data-layout'):
            self.result = json.loads(dict(attrs)['data-layout'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('/tmp/meta-controls-qa'))
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    chromium=shutil.which('chromium') or shutil.which('chromium-browser')
    if not chromium:raise SystemExit('Run this inside the existing Docker image (Chromium required)')
    page_html=HTML.replace('<script>','<script>window.fetch=async()=>({status:401,ok:false});',1).replace('</body>','<script>'+FIXTURE+'</script></body>')
    with tempfile.TemporaryDirectory() as d:
        page=Path(d)/'presets.html';page.write_text(page_html,encoding='utf-8')
        for width in (320,390,768,1280):
            result=subprocess.run([chromium,'--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
                '--hide-scrollbars','--virtual-time-budget=1500','--force-device-scale-factor=1',f'--window-size={width},900',
                f'--screenshot={args.output_dir.resolve()/(str(width)+".png")}','--dump-dom',page.as_uri()],
                capture_output=True,text=True,timeout=45,check=True)
            parsed=MetricsParser();parsed.feed(result.stdout);m=parsed.result
            assert m is not None,result.stderr[-1500:]
            assert m['width']==width,m
            assert m['scrollWidth']<=m['width'] and not m['outside'],m
            assert len(m['chips'])==4 and sum(c['selected']=='true' for c in m['chips'])==1,m
            assert all(c['grow']=='0' and c['height']>=44 for c in m['chips']),m
            assert all(h>=44 for h in m['heights']),m
            assert m['selected']=='ファンタジーカップ' and not m['defaultDisabled'],m
            (args.output_dir/(str(width)+'.json')).write_text(json.dumps(m,ensure_ascii=False,indent=2))
            print(json.dumps(m,ensure_ascii=False))

if __name__=='__main__':main()
