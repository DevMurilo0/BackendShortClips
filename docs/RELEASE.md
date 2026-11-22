# Preparação de release

Nenhum deploy, push ou alteração remota de configuração foi autorizado nesta
rodada. Branch backend `fix/sandbox-pipeline-validation`; frontend em worktree
`../ShortClips_Cloud`, branch `fix/cloud-download-integration`, baseada na branch
remota `feat/smart-clips-vercel`. A cópia `ShortForge_Local/main` foi preservada.

1. Revisar diffs e testes. Autenticação atual serve a um único operador; não
   anunciar serviço multiusuário sem autorização por dono e rate limiting.
2. Ensaio isolado aprovado: um vencedor no mutex real, artefatos recuperados e
   limpeza confirmada (CLOUD-INTEGRATION.md). Repetir operações pagas somente
   após nova autorização. Antes de qualquer deploy Preview, aprovar a proposta
   PREVIEW-HOMOLOGATION.md.
3. Construir/homologar imagem OCI linux/amd64 no projeto correto, com digest de
   base e pacotes revisados; só então usar `SHORTFORGE_SANDBOX_IMAGE`. Sem Docker
   local a imagem não foi produzida. Não fazer snapshot contendo jobs/segredos.
4. Resolver SLA de exclusão física em 24h: scheduler autenticado mais frequente
   e custos correspondentes exigem decisão. Schedules beta permite 15min no Hobby;
   usar corte antecipado e monitoramento. Ver RETENTION-24H.md; cron diário é fallback.
5. Criar Preview isolado após aprovação de consumo, com segredos de teste
   próprios e Blob privado de teste ou namespace segregado. Nunca substituir
   indiscriminadamente variáveis existentes. Production/Preview mantêm token RW
   conectado; OIDC Development não substitui a necessidade de credencial de
   storage dentro da VM.
6. Confirmar build misto Python/Node, rewrites (download deve ir à Function JS),
   cold start, callback, CORS, chave incorreta, timeout/cancelamento, expiração,
   MP4/ZIP por links temporários, frontend em desktop e celular. Confirmar que
   `worker/**` e seu lock foram incluídos na Function sem dependências pesadas.
7. Testar uma fonte YouTube autorizada: rede/permissão da origem não foi validada
   nesta rodada. Falha do YouTube não deve virar sucesso falso ou contorno de
   acesso. Testar detecção automática de facecam em conteúdo adequado.
8. Após homologação, solicitar autorização explícita para liberação e definição
   de `SHORTFORGE_ENGINE=sandbox` em Production. Fazer deploy controlado com
   referência ao commit aprovado e rollback; monitorar Vercel Usage.

O build local foi aprovado com Python 3.14, Node.js 26 e uv 0.13.9. O CLI gerou
`pyproject.toml`/`uv.lock`; foram revisados para versionar o runtime da Function.
Depois do build rode `python scripts/check_build.py` para conferir o artefato.

Comandos de build local (não publicam):

```bash
npx vercel@65.16.0 project inspect backend-short-clips --scope murilo15 --non-interactive
npx vercel@65.16.0 pull --yes --environment=preview --scope murilo15 --project backend-short-clips
npx vercel@65.16.0 build --scope murilo15 --project backend-short-clips
```

O pull guarda segredos em `.vercel/`, excluída de Git/deploy. Tokens sensíveis
podem vir como `[SENSITIVE]`; não usar placeholder como credencial em teste real.
Não publicar arquivos de ambiente nem artefatos locais de autenticação.
