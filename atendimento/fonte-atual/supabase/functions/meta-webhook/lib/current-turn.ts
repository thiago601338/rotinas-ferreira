/** Group a customer's current message burst; old unresolved questions stay with humans. */
export function currentBurst(rows:any[],gapMs=120000){
 const sorted=[...rows].sort((a,b)=>Date.parse(a.created_at)-Date.parse(b.created_at));
 let start=sorted.length-1;
 while(start>0&&Date.parse(sorted[start].created_at)-Date.parse(sorted[start-1].created_at)<=gapMs)start--;
 // A delayed '?' or 'Valor?' still refers to the previous pending request.
 const followup=sorted.slice(Math.max(0,start)).map(r=>r.text_content??r.raw_payload?.text??'').join(' ').trim();
 if(start>0&&/^(?:[?!.\s]+|(?:qual (?:o )?)?(?:valor|preco|preço)\s*[?!.]*)$/i.test(followup)&&Date.parse(sorted.at(-1).created_at)-Date.parse(sorted[start-1].created_at)<=30*60000){
  start--;
  while(start>0&&Date.parse(sorted[start].created_at)-Date.parse(sorted[start-1].created_at)<=gapMs)start--;
 }
 return {current:sorted.slice(Math.max(0,start)),older:sorted.slice(0,Math.max(0,start))};
}
export function freshCatalogQuestion(text:string){
 const n=text.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
 return /^(?:(?:tem|voces tem|voce tem|quero (?:ver|comprar)|gostaria de (?:ver|comprar)|me (?:mande|mostre))\s+(?:um |uma |algum |alguma )?)?(?:vestidos?|conjuntos?|blusas?|calcas?|saias?|macacoes?)\b/.test(n)
 && !/\b(esse|essa|desse|dessa|mesmo|mesma|da foto|do story)\b/.test(n);
}
