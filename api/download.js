import { head, issueSignedToken, presignUrl } from '@vercel/blob';
import { timingSafeEqual } from 'node:crypto';

/** Signed downloads are issued only after a Bearer key is provided. */
const FILE = /^shortforge\/jobs\/20\d{2}-(?:0[1-9]|1[0-2])\/[a-f0-9]{32}\/output\/(?:short_0[1-5]\.mp4|shorts_prontos\.zip)$/;

export default async function handler(req, res) {
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
  const expected = process.env.SHORTFORGE_PUBLIC_ACCESS_KEY;
  // Tempo constante para não divulgar detalhes da chave de acesso.
  const supplied=(req.headers.authorization || '').replace(/^Bearer /, '');
  const equal=Boolean(expected) && Buffer.byteLength(supplied)===Buffer.byteLength(expected) &&
    timingSafeEqual(Buffer.from(supplied),Buffer.from(expected));
  if (!equal)
    return res.status(401).json({error:'Chave de acesso inválida.'});
  const pathname = req.query.pathname;
  if (typeof pathname !== 'string' || !FILE.test(pathname))
    return res.status(400).json({error:'Caminho do arquivo inválido.'});
  try {
    const meta=await head(pathname,{access:'private'});
    if(!meta) return res.status(404).json({error:'Arquivo não encontrado.'});
    const now=Date.now();
    const created=new Date(meta.uploadedAt).getTime();
    if(!Number.isFinite(created)||now-created>=24*60*60*1000)
      return res.status(410).json({error:'Este Short expirou após 24 horas.'});
    const token=await issueSignedToken({
      pathname, operations:['get'], validUntil:now+10*60*1000
    });
    const result=await presignUrl(token,{
      operation:'get', pathname, access:'private',
      validUntil: now+5*60*1000
    });
    return res.status(200).json({
      url:result.presignedUrl, expires_in_seconds:300
    });
  } catch (err) {
    return res.status(503).json({
      error:'Não foi possível gerar o link temporário de download.'
    });
  }
}
