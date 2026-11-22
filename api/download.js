import { head, get, issueSignedToken, presignUrl } from '@vercel/blob';
import { timingSafeEqual } from 'node:crypto';

/** Signed downloads are issued only after a Bearer key is provided. */
const FILE = /^jobs\/20\d{2}-(?:0[1-9]|1[0-2])\/[a-f0-9]{32}\/output\/(?:short_0[1-5]\.mp4|shorts_prontos\.zip)$/;

export function createHandler(storage = { head, get, issueSignedToken, presignUrl }) {
return async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  const allowed = (process.env.SHORTFORGE_FRONTEND_ORIGIN ||
    'https://short-clips-tan.vercel.app').replace(/\/$/, '');
  const origin = (req.headers.origin || '').replace(/\/$/, '');
  if (origin === allowed) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary','Origin');
  }
  if (req.method === 'OPTIONS') {
    if (origin !== allowed) return res.status(403).json({error:'Origem não permitida.'});
    res.setHeader('Access-Control-Allow-Methods','GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers','Authorization');
    return res.status(204).end();
  }
  if (req.method !== 'GET') return res.status(405).json({error:'Método inválido.'});
  if (origin && origin !== allowed) return res.status(403).json({error:'Origem não permitida.'});
  if (process.env.SHORTFORGE_ENGINE !== 'sandbox')
    return res.status(503).json({error:'Motor de processamento desativado.'});
  const expected = process.env.SHORTFORGE_PUBLIC_ACCESS_KEY;
  // Tempo constante para não divulgar detalhes da chave de acesso.
  const supplied=(req.headers.authorization || '').replace(/^Bearer /i, '');
  const equal=Boolean(expected && expected.length >= 32) && Buffer.byteLength(supplied)===Buffer.byteLength(expected) &&
    timingSafeEqual(Buffer.from(supplied),Buffer.from(expected));
  if (!equal)
    return res.status(401).json({error:'Chave de acesso inválida.'});
  const root=process.env.SHORTFORGE_STORAGE_PREFIX || 'shortforge';
  const environment=process.env.VERCEL_ENV;
  if (!/^shortforge(?:-preview\/[a-z0-9][a-z0-9-]{0,47})?$/.test(root) ||
      (environment==='preview' && !root.startsWith('shortforge-preview/')) ||
      (environment==='production' && root!=='shortforge'))
    return res.status(503).json({error:'Namespace de armazenamento não configurado para este ambiente.'});
  const pathname = req.query.pathname;
  const ownFile=new RegExp('^'+root+'/'+FILE.source.slice(1));
  if (typeof pathname !== 'string' || !ownFile.test(pathname))
    return res.status(400).json({error:'Caminho do arquivo inválido.'});
  try {
    const statePath = pathname.replace(/output\/[^/]+$/, 'state.json');
    const stored = await storage.get(statePath, {access:'private', useCache:false});
    if (!stored || stored.statusCode !== 200)
      return res.status(404).json({error:'Tarefa não encontrada.'});
    const state = await new Response(stored.stream).json();
    const now = Date.now();
    const deadline = Date.parse(state.expires_at);
    if (!Number.isFinite(deadline) || now >= deadline || state.status === 'expired')
      return res.status(410).json({error:'Este Short expirou após 24 horas.'});
    if (!['completed','partial'].includes(state.status))
      return res.status(409).json({error:'Resultados ainda não disponíveis.'});
    const belongs = state.zip_path === pathname ||
      (state.clips || []).some(c => c.status === 'ready' && c.blob_path === pathname);
    if (!belongs) return res.status(404).json({error:'Arquivo não pertence à tarefa.'});
    const meta = await storage.head(pathname);
    if (!meta) return res.status(404).json({error:'Arquivo não encontrado.'});
    const validUntil = Math.min(deadline, now + 5*60*1000);
    const token=await storage.issueSignedToken({
      pathname, operations:['get'], validUntil
    });
    const result=await storage.presignUrl(token,{
      operation:'get', pathname, access:'private',
      validUntil
    });
    return res.status(200).json({
      url:result.presignedUrl, expires_in_seconds:Math.floor((validUntil-now)/1000)
    });
  } catch (err) {
    return res.status(503).json({
      error:'Não foi possível gerar o link temporário de download.'
    });
  }
}

}
export default createHandler();
