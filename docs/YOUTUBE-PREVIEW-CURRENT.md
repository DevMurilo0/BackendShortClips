# Homologação YouTube atual — 22/11/2026

## Resultado

Preparação local concluída; deploy e geração **não executados**. Não existe
MP4, ZIP ou legenda de YouTube homologado nesta rodada. Os testes sintéticos
históricos não foram usados como evidência atual.

Branch backend: `feat/preview-authorized-youtube`, base `c525c58`.
A alteração preexistente de `.gitignore` foi preservada sem incorporá-la ao commit.
Frontend local: `../ShortClips_Cloud`, branch `fix/cloud-download-integration`,
commit `160c5ce`, acompanhando `origin/feat/smart-clips-vercel`, um commit à frente.
Nenhuma alteração ou publicação desse frontend foi realizada nesta rodada.

## Bloqueios anteriores à criação de recursos

1. Link individual autorizado ainda não fornecido. Foi solicitado junto da
   confirmação de direitos. Nenhum link de teste foi inventado ou baixado.
2. Equipe `murilo15` confirmada pela CLI como Hobby ativo, mas o consumo atual
   não pôde ser obtido. `vercel billing usage --json` informou dados indisponíveis;
   o conector de billing retornou `404 costs_not_found`. A consulta team-wide de
   `vercel.sandbox.cpu_total_time_ms` retornou `payment_required`, exigindo
   Observability Plus. Não foi feito upgrade. Necessário obter o consumo/limites
   atuais pelo painel Usage, inclusive Blob, antes de criar recursos.
3. O frontend publicado diverge do contrato atual: usa `blob_path`/`zip_path`,
   removidos pelo backend em favor de `download_endpoint`/`zip_download_endpoint`.
   Também não oferece reprodução cloud na página. A cópia local `160c5ce` já
   contém adaptação desses caminhos e playback, mas não foi homologada com
   processamento real. Sua publicação requer autorização adicional do usuário.
4. Proteção Vercel e callback continuam dependendo de bypass privado válido,
   gerenciado pela Vercel, e de verificação de acesso pelo navegador. O segredo
   Blob no pull Preview é `[SENSITIVE]`; não é credencial utilizável localmente.
   A existência da variável remota não comprova injeção funcional no worker.

## Mudanças locais

- Perfil opt-in `SHORTFORGE_PREVIEW_AUTHORIZED_YOUTUBE` fixa a origem canônica
  autorizada; `SHORTFORGE_PREVIEW_RIGHTS_CONFIRMED=1` é declaração privada do
  operador. Exige Preview e namespace exclusivo, e recusa combinar fonte sintética.
- Pedido restrito a um Short de 30s, 720p, facecam manual. Mantidos mutex, quota,
  reserva create-only `integration/once.json`, uma única tentativa de criação,
  2 vCPUs, 4096 MB, persistent=false e teto remoto de 600s.
- Worker confere origem canônica e vídeo autorizado, metadados de vídeo gravado
  de 30–120s e tamanho conhecido até 128 MiB antes de baixar mídia. yt-dlp recebe
  limite de 128 MiB no perfil controlado. Tamanho desconhecido permanece sujeito
  ao limite de download; não é garantia de tamanho antecipada. Nenhum cookie,
  proxy ou mecanismo de contorno de acesso foi acrescentado.
- URLs com playlist/index e IDs duplicados são recusadas pelo gateway.
- Callback usa `https://` + `VERCEL_URL` do próprio deployment; URL explícita
  divergente falha. Não é necessário descobrir URL e publicar pela segunda vez.
  Em Preview deve-se omitir o default Production de SHORTFORGE_PUBLIC_API_URL.
- `[SENSITIVE]` em credenciais impede a configuração do motor.
- Removido cron do pacote vercel.json de ensaio. Nenhum schedule criado.
- Perfil normal de até cinco cortes e 42min permanece no código e não foi usado.
  O Preview sem perfil controlado permanece fechado. A reserva consumida bloqueia
  outra tarefa no mesmo namespace; não trocar namespace sem nova autorização.

## Evidência executada agora

- `python -m unittest discover -s tests -v` no venv
  `/tmp/shortforge-real-validation`: **81 testes, OK, 2 skipped**. Os testes
  opcionais de mídia não foram executados. Testes de orchestration usam mocks;
  não comprovam VM, callback nem armazenamento remotos.
- `npm ci`: concluído, auditoria zero vulnerabilidades; `npm test`: **14/14**.
- `git diff --check`: aprovado.
- CLI confirmou ID `prj_6q8UJw3x8PLQzdxAOMdnovAwqT1P`, owner murilo15, raiz `.`.
- Metadados Preview: Blob conectado e variável RW remota Secret/Hidden. CLI
  get-store confirmou store `shortforge-private`, acesso **Private**, região gru1.
  Sem leitura/escrita de objetos de usuários.
- Frontend publicado: https://short-clips-tan.vercel.app — carregado de verdade
  em Chromium, larguras 390 e 1280px, sem overflow horizontal ou pageerror.
  Envio permaneceu bloqueado; backend indisponível foi comunicado. Nenhum POST.
  Evidência: `current-live-ui-check.json`; screenshots locais em
  `/tmp/shortforge-current-ui-{390,1280}.png`.
- HTTP somente leitura: `current-http-readonly.json`. Production health 200,
  gateway/ready=false; download e latest sem chave 401; preflight da origem
  autorizada 204 com allow-origin exato; origem não autorizada 403.
- Preview histórico https://backend-short-clips-ipltw3gpb-murilo15.vercel.app
  retornou HTML protegido ao acesso direto, não health JSON. Não é novo Preview.

## Consumo e pendências

Novos deployments: **0**. Novos Sandboxes: **0**. Novas gerações: **0**.
Nenhum recurso de computação foi criado para esta rodada, portanto não houve VM
para encerrar. Não foi feita auditoria global de máquinas preexistentes/órfãs.
Não há consumo oficial/fatura de Sandbox obtido nesta rodada. A hipótese superior
para uma VM autorizada é 1200 CPU-s (2 vCPU × 600s) e 0,667 GiB-h de memória;
trata-se de envelope conservador, não consumo medido nem comprovação de franquia.
Leituras HTTP/API feitas não equivalem a uma declaração de custo faturado zero.

Permanecem sem homologação: novo Preview READY, build final, HTTP ativo,
autenticação com credenciais reais, navegador através da proteção, origem YouTube,
FFmpeg/áudio/legendas, callback, assinatura e playback, downloads MP4/ZIP,
encerramento real do worker e retenção física de até 24h.
Nenhum push/deploy/alteração de variável remota ou de Production foi feito.
Production continua inacessível para geração no health observado.
