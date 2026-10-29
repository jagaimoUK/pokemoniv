/* Shared pure logic. The APK bundles these exact bytes; no engine/network dependency. */
(function(root,factory){const api=factory();if(typeof module==='object')module.exports=api;else root.Flashcards=factory();})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const DAY=86400000;
  const key=c=>[c.species,c.fast,c.charged].join('|');
  function counts(gain,cost,n=5){
    if(!Number.isFinite(gain)||gain<=0||gain>100||!Number.isFinite(cost)||cost<=0||cost>100)throw Error('技のエネルギーが不正です');
    let energy=0;const result=[];
    for(let i=0;i<n;i++){let count=0;while(energy<cost){energy=Math.min(100,energy+gain);count++;}energy-=cost;result.push(count);}
    return result;
  }
  function signature(c,moves){const f=moves[c.fast],g=moves[c.charged];return JSON.stringify([f?.gain,g?.cost]);}
  function cards(rows,catalog){
    const result=new Map();let invalid=0;
    for(const row of rows||[]){
      const p=catalog.species[row.species];
      for(const fast of row.fast||[])for(const charged of row.charged||[]){
        const c={species:row.species,fast,charged};
        if(!p||!p.fast.includes(fast)||!p.charged.includes(charged)){invalid++;continue;}
        try{counts(catalog.moves[fast]?.gain,catalog.moves[charged]?.cost);result.set(key(c),c);}catch(_){invalid++;}
      }
    }
    return {items:[...result.values()],invalid};
  }
  function deckCards(deck,catalog){
    const compiled=cards([...(deck.rows||[]),...(deck.extra||[])],catalog);
    const excluded=new Set(deck.excluded||[]);
    return {...compiled,items:compiled.items.filter(c=>!excluded.has(key(c)))};
  }
  function stateFor(card,stored,moves){
    const answer=signature(card,moves);
    // Names/rank changes keep history. Energy changes invalidate just that answer.
    if(!stored||stored.signature!==answer)return {id:key(card),signature:answer,reps:0,ease:2.5,interval:0,due:0,lapses:0,seen:0};
    return {...stored};
  }
  function review(state,correct,now=Date.now()){
    if(typeof correct!=='boolean'||!Number.isFinite(now))throw Error('評価が不正です');
    const s={...state,seen:state.seen+1,last:now};
    // Two-button adaptation of SM-2: correct=q4, review=q2, plus a 10min relearning step.
    const q=correct?4:2;
    s.ease=Math.max(1.3,state.ease+0.1-(5-q)*(0.08+(5-q)*0.02));
    if(correct&&state.seen&&state.due>now)return s; // Early practice never postpones a scheduled review.
    if(correct){s.reps++;s.interval=s.reps===1?1:s.reps===2?6:Math.ceil(state.interval*state.ease);s.due=now+s.interval*DAY;}
    else{s.reps=0;s.interval=0;s.lapses++;s.due=now+600000;}
    return s;
  }
  function select(items,stored,moves,limit,now=Date.now()){
    if(![10,30,50].includes(limit))throw Error('10・30・50問から選択してください');
    const buckets=[[],[],[]];
    for(const c of items){const s=stateFor(c,stored[key(c)],moves);const group=s.seen?(s.due<=now?0:2):1;buckets[group].push({c,s});}
    // Overdue first; hard cards win ties. New cards have a stable order.
    buckets[0].sort((a,b)=>b.s.lapses-a.s.lapses||a.s.due-b.s.due||key(a.c).localeCompare(key(b.c)));
    buckets[1].sort((a,b)=>key(a.c).localeCompare(key(b.c)));
    buckets[2].sort((a,b)=>b.s.lapses-a.s.lapses||a.s.due-b.s.due);
    return buckets.flat().slice(0,limit).map(x=>x.c);
  }
  function dueInfo(decks,catalog,stored,now=Date.now()){
    const all=new Map();for(const d of decks)for(const c of deckCards(d,catalog).items)all.set(key(c),c);
    let next=null,due=0;
    for(const c of all.values()){const s=stateFor(c,stored[key(c)],catalog.moves);if(!s.seen)continue;if(s.due<=now)due++;if(next===null||s.due<next)next=s.due;}
    return {next,due};
  }
  function mergeDecks(local,remote){
    const existing=new Map(local.map(d=>[d.id,d]));const result=[];
    for(const d of remote){const old=existing.get(d.id);if(d.id==='meta:legacy'&&old?.revision&&!d.revision){result.push(old);existing.delete(d.id);continue;}result.push({...d,extra:old?.extra||[],excluded:old?.excluded||[]});existing.delete(d.id);}
    // A private source is retained offline until an authenticated refresh confirms its removal.
    for(const d of existing.values())result.push(d);
    return result;
  }
  return {DAY,key,counts,cards,deckCards,signature,stateFor,review,select,dueInfo,mergeDecks};
});
