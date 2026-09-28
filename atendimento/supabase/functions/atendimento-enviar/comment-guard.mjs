const META_ID = /^\d{5,40}$/;
const username = (value) => typeof value === 'string' && /^[A-Za-z0-9._]{1,30}$/.test(value) ? value.toLowerCase() : null;

// A sincronização pode estar atrasada. Esta leitura deve acontecer em cada envio,
// sem cache de respostas e sem seguir URLs de paginação que possam conter token.
export async function commentReplyGuard(job, token, config, fetcher, readJson) {
  const signal = AbortSignal.timeout(15000);
  const base = `https://graph.instagram.com/${config.version}/`;
  async function get(path, fields, after = null) {
    const url = new URL(base + path);
    url.searchParams.set('fields', fields);
    if (path.endsWith('/replies')) url.searchParams.set('limit', '100');
    if (after) url.searchParams.set('after', after);
    const response = await fetcher(url.toString(), {
      method: 'GET', redirect: 'error', signal,
      headers: { Authorization: `Bearer ${token}` },
    });
    const data = await readJson(response);
    if (!response.ok || !data || data.error) throw Error('consulta_invalida');
    return data;
  }
  try {
    // Resolve também o ID canônico: Instagram Login pode devolver um ID
    // diferente do configurado. Username serve aos replies sem from.id.
    const account = await get('me', 'id,username');
    const shopUsername = username(account.username);
    if (typeof account.id !== 'string' || !META_ID.test(account.id) || !shopUsername) throw Error('conta_nao_verificada');
    const ids = new Set([config.accountId, account.id]);
    const cursors = new Set();
    let after = null;
    for (let pages = 0; pages < 100; pages++) {
      const page = await get(`${job.commentId}/replies`, 'id,username', after);
      if (!Array.isArray(page.data)) throw Error('respostas_invalidas');
      for (const reply of page.data) {
        const id = reply?.from?.id;
        const names = [username(reply?.username), username(reply?.from?.username)].filter(Boolean);
        if (ids.has(id) || names.includes(shopUsername)) return 'equipe_respondeu';
        if (!META_ID.test(id ?? '') && !names.length) throw Error('autor_nao_verificado');
      }
      if (page.paging != null && (typeof page.paging !== 'object' || Array.isArray(page.paging))) throw Error('paginacao_invalida');
      if (page.paging?.next == null) return null;
      if (typeof page.paging.next !== 'string' || !page.paging.next) throw Error('paginacao_invalida');
      const next = new URL(page.paging.next);
      if (next.origin !== 'https://graph.instagram.com' || next.username || next.password
        || next.pathname !== `/${config.version}/${job.commentId}/replies`) throw Error('paginacao_invalida');
      after = page.paging.cursors?.after ?? next.searchParams.get('after');
      if (typeof after !== 'string' || !after || after.length > 4000 || cursors.has(after)) throw Error('cursor_invalido');
      cursors.add(after);
    }
    throw Error('paginacao_incompleta');
  } catch {
    // Falha de leitura acontece antes do POST; nunca expor corpo, URL ou token.
    return 'comentario_nao_verificado';
  }
}
