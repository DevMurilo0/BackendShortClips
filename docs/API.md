# Contrato da API ShortForge

Base: `https://backend-short-clips.vercel.app`. CORS permite somente
`SHORTFORGE_FRONTEND_ORIGIN`. Todo endpoint de usuário, exceto health, exige
`Authorization: Bearer <segredo single-owner>`. Não há segregação multiusuário;
a mesma chave autoriza todas as tarefas deste operador.

- `GET /api/health`: público, `ok`, `mode`, `ready`, `limits`. Ready indica
  configuração presente, não atestado de conectividade/saúde do worker.
- `POST /api/jobs`: `{url, count?:5, length?:45, resolution?:720,
  facecam?:"auto", manual_box?:[x,y,w,h]}`. Apenas YouTube HTTPS individual;
  count=1..5, length=30..45, resolution=720. Região manual em porcentagens
  0..100. Backend fixa modelo base. Retorna 201 `{job}`; entradas inválidas 400,
  motor indisponível 503, outra tarefa 409, quota mensal 429.
- `GET /api/jobs/latest`: `{job}`; 404 quando inexistente.
- `GET /api/jobs/<32 hex>`: estado direto, sem envelope; 404 se inexistente.
- `POST /api/jobs/<id>/cancel`: corpo `{}`; encerra Sandbox antes de persistir
  `cancelled`. Retorna `{job}`. Se a VM não puder ser encerrada, 502 e lock mantido.
- `POST /api/jobs/<id>/retry`: 501 no motor cloud. Frontend esconde retry/prévia
  local em modo remoto. Repetição seletiva é uma funcionalidade local existente.
- `GET /api/usage`: quotas persistentes e estimativas; não equivale a fatura.
- `GET /api/download?pathname=<path retornado em download_endpoint>`: Bearer
  obrigatório. Responde `{url, expires_in_seconds}`. Cliente deve fazer fetch
  autenticado **ao clicar** e abrir o URL retornado; não guardar URL por horas.
  URLs assinadas são credenciais temporárias de leitura daquele único arquivo;
  não são URLs públicas permanentes nem contêm o token RW.
- `POST /api/internal/finished`: somente serviço, header
  `X-ShortForge-Worker-Secret`, JSON `{id}`. Não usar chave do usuário.
- `GET /api/cleanup`: somente cron, `Authorization: Bearer <CRON_SECRET>`.
  Remoção física de artefatos expirados; preserva auditoria/quota.

Estados: `queued`, `running`, `completed`, `partial`, `failed`, `cancelled`,
`expired`. O campo `stage` detalha progresso; `uploading` ainda não é pronto.
Somente artefatos enviados recebem `ready` e `download_endpoint`. Estado público
inclui `zip_download_endpoint` quando o ZIP foi enviado. Não há blob_path direto
nos clips nem credenciais Sandbox. O endpoint de download contém o pathname
necessário para autorizar a assinatura, e verifica o vínculo com a tarefa final.

Quando `expired`, remover vídeos/ZIP exibidos e parar polling. Falhas e parcial
mostram `errors`; parcial permite baixar os artefatos válidos. Cancelado também
é terminal. Polling de ~7s reduz leituras de Blob; sempre usar no-store e tratar
401/403/404/429/5xx sem anunciar processamento concluído.
