# Validação ShortForge — 22/11/2026

Estado: implementação local corrigida; **não liberado para produção**. Nenhum
Sandbox desta rodada foi criado e nenhum deploy/push foi executado. A aprovação
do ensaio de nuvem está pendente. Não confundir os testes abaixo com certificação
de funcionamento em Vercel.

## Evidências executadas

- Ambiente solicitado: `/tmp/shortforge-sdk-check`, CPython 3.14.10. Instalação de
  `requirements.txt`, importação real `vercel.sandbox`, `vercel.blob` e
  `SandboxResources`: aprovadas. `enabled()` retornou `False`.
- 24 testes originais: aprovados antes das mudanças.
- 47 testes Python após correções: aprovados, incluindo os dois testes reais de
  mídia habilitados com `SHORTFORGE_RUN_MEDIA_TESTS=1`. Demais testes de serviços
  usam simulador de Blob ou mocks; não comprovam atomicidade no serviço real.
- 9 testes Node: autorização, pertencimento de artefato, expiração, tarefa
  cancelada/em upload e falha de Blob. Serviços simulados.
- FFmpeg local: fonte sintética de 46s, resultado 45s, 720×1280, áudio, legenda
  queimada confirmada em pixels decodificados, caminhos com acentos/apóstrofos e
  remoção de temporários. Cancelamento de subprocesso real também aprovado.
- Pipeline local completo: `scripts/local_pipeline_check.py`, sem mocks de mídia:
  seleção por energia, OCR real, facecam **manual**, Whisper base CPU/int8,
  11 blocos de legendas, MP4 de 30s 720×1280 com áudio e ZIP íntegro. Fonte criada
  por FFmpeg/espeak. Não valida detecção automática de rosto, YouTube nem Blob.
- Uma primeira fonte sintética de 32s falhou ao reconhecer fala no corte iniciado
  em 2s. Diagnóstico: áudio/VAD presentes; Whisper descartou aquele recorte.
  O teste passou com fonte de 30s preservando o início. Os critérios do Whisper
  foram preservados. Trechos sem fala agora tentam outro candidato disponível,
  assim como cenas inadequadas; nunca recebem legendas inventadas.
- Frontend: Chromium headless existente, Playwright com API simulada, larguras
  375 e 1280px: cinco cards, autorização no pedido de download, controles de
  vídeo, cancelado/expirado, sem overflow horizontal nem exceções JavaScript.
  Não foi validado playback real em navegador/dispositivo físico.
- `npm audit`: zero vulnerabilidades após override de `zod` para 4.6.6.
- HTTP de produção, somente leitura: `/api/health` respondeu 200, mode=gateway,
  ready=false; `/api/download` respondeu 401 sem chave. Frontend `config.js`
  aponta para `https://backend-short-clips.vercel.app`.
- Vercel CLI 65.16.0 confirmou projeto `murilo15/backend-short-clips`, região
  Sandbox iad1, raiz `.`. Conector Vercel respondeu 404; inspeção pela CLI funcionou.
- Pull **Preview** guardado em `.vercel/`, ignorado por Git. Um segredo sensível
  veio como placeholder; não foi substituído nem impresso. `.env.local` original
  contém OIDC/ID do store, sem token estático RW. Nenhuma variável remota alterada.

- Build local de Preview aprovado pela CLI 65.16.0 (uv 0.13.9), com Functions
  Python 3.14 e Node.js 26 separadas. Corrigidos preset misto e rewrites explícitos.
  A validação do artefato verifica worker/lock incluídos, exclusão de arquivos de
  ambiente, testes/modelos e ausência de dependências de mídia na Function.
  Falhas intermediárias de build: rewrite wildcard/preset anterior e uv ausente;
  corrigidas localmente. Não houve deploy nem validação HTTP de um novo Preview.

## Correções e garantias do código

- Worker e pipeline versionados neste backend, derivados da cópia local do repo
  `DevMurilo0/ShortClips` (main, commit `d0a6218a043ae435c2b9886fe6ee86f09981ede0`). A API envia apenas código e manifesto do deploy,
  sem clonar branches mutáveis nem credenciais Git dentro da VM.
- `create_command` inicia sem esperar renderização. SDK Python real inspecionado:
  `create_sandbox`, `SandboxResources`, `box.fs.write_bytes`, `create_command`,
  `stop`, streaming Blob e deleção condicional. Importar não é executar na nuvem.
- Quota sob mutex global, reserva persistente antes de criar VM, mês capturado
  uma vez. Inicializações falhas consomem reserva por segurança. Máximo 3/mês,
  inclusive após reinício, limpeza e troca de instância.
- Lock create-only e remoção com ETag da **mesma leitura**. Falhas ambíguas de
  criação/encerramento mantêm lock; recuperação conservadora após 48min por nome
  determinístico. Ensaio real de concorrência incluído no smoke test pendente.
- Leituras de estado/mutex usam URL privada com `cache=0`: Python Blob 0.6.2 não
  oferece `useCache`, mas aceita a opção oficial no URL. Token é enviado pelo SDK
  no header, nunca no URL. `cache_control_max_age=0` sozinho não garante isso.
- Backend valida HTTPS/hosts/ID individual YouTube; não aceita URL arbitrária,
  playlist, credenciais, portas não padrão nem fonte local/Blob do cliente.
  Fonte sintética é configuração privada do operador, sem rota pública.
- Até 5 cortes, 30–45s, 720×1280, 2 vCPUs/4096 MB, 42min, um job por vez.
  FFmpeg/Whisper/OpenCV limitados a dois threads. Arquivo individual limitado a
  1 GiB no worker; downloads yt-dlp limitados por tamanho e tempo.
- Nenhum estado `completed` publicado antes dos uploads. Upload parcial preserva
  MP4s válidos; ZIP inclui apenas MP4s enviados. Falha do ZIP não invalida MP4s.
- Callback autenticado ocorre depois do estado final e limpeza local. Consulta
  posterior e timeout são recuperação; callback real ainda não foi testado.
- Download requer Bearer e arquivo presente no estado final da própria tarefa.
  URL assinada somente de leitura e um arquivo, válida por até 5min, nunca além
  da expiração da tarefa. Sem token RW no navegador.
- Autenticação continua **single-owner** (um segredo informado manualmente).
  Não é um sistema multiusuário; liberar vários usuários exige identidade,
  autorização por dono e rate limiting por identidade antes da abertura pública.

## Retenção: limite ainda não resolvido para liberação

Acesso expira 24h após criação da tarefa. Consulta de tarefa expirada e cron
apagam fisicamente todos os artefatos, em lotes, preservando pequeno tombstone e
quota. A quota/uso mensal não somem junto dos MP4s.

**O cron Hobby diário permite resíduo físico de até ~48h desde a criação.**
Não atende exclusão física no instante de 24h sem uma consulta. Nenhuma mudança
paga de agendamento foi feita. Para SLA físico de ~24h, escolher/agendar limpeza
mais frequente em plano compatível ou scheduler externo autenticado. Retenção
exata requer execução confiável/retries; registrar atraso e alertas.

Blob ganhou `ttlDays` no JS SDK 2.9.0, mas o Python 0.6.2 não expõe essa opção.
Além disso, a documentação da implementação informa avaliação diária à meia-noite
UTC: TTL nativo não garante deleção física exatamente em 24h. Não foi adicionado
um parâmetro inexistente ao Python nem alegada uma garantia inexistente.

## Sandbox econômico

`worker/Dockerfile` é um template OCI linux/amd64 para VCR: FFmpeg, Tesseract,
fontes e ambiente Python pré-instalados, `--no-install-recommends`, sem Git e sem
cache apt/pip. `SHORTFORGE_SANDBOX_IMAGE` permite escolher referência/digest do
projeto depois de homologar. O caminho `/opt/shortforge/bin/python` evita apt/pip
em cada vídeo. Locks Python versionam as dependências testadas.

**Imagem não construída/publicada** (Docker não disponível localmente). Antes de
homologar: fixar digest da base, resolver versões dos pacotes Debian, medir
inicialização e renderização, considerar pré-carregar modelo base e OCR com
revisões/checksums fixos. Não houve aumento de recursos nem criação de snapshots.
O modo padrão ainda instala dependências numa VM efêmera; falhas após instalação
do pequeno SDK Blob são registradas. Falha anterior a isso depende de reconciliação.

## Ensaio real preparado, ainda não executado

`scripts/cloud_smoke.py` sem `--execute` não faz chamadas remotas. Com aprovação:

```bash
/tmp/shortforge-sdk-check/bin/python -m pip install -r scripts/requirements-test.txt
/tmp/shortforge-sdk-check/bin/python scripts/cloud_smoke.py --execute
```

Guardas: OIDC deve identificar murilo15/backend-short-clips e ter validade >10min;
SDK pode usar as credenciais normais de CLI/ambiente; região iad1 explícita;
2vCPU/4GB, 600s, persistent=false. Gera fala/cena sintética local, input privado,
worker real, seleção/OCR/Whisper/render, upload/recuperação MP4 e ZIP, ffprobe,
status e métricas; para/destroi VM e apaga somente `shortforge/integration/<UUID>/`.
Antes da VM verifica oito criações Blob simultâneas de um mesmo pathname: exige
um vencedor. Não altera `shortforge/jobs`, quota real, LATEST, motor ou variáveis
remotas. Grava relatório sem segredos em `docs/cloud-smoke-result.json`.

Consumo máximo de computação: 0,333 vCPU-h + 0,667 GB-h; referência Pro iad1
aproximada US$0,057, mais operações Blob/transferência. No Hobby usa franquia.
Instalação fria pode baixar centenas de MB de dependências/modelo. Não é custo
observado nem promessa de preço. Callback HTTP público e autenticação ponta a
ponta exigirão depois um Preview configurado com segredos de teste.

## Reprodução local

```bash
python -m venv /tmp/shortforge-sdk-check
/tmp/shortforge-sdk-check/bin/python -m pip install -r requirements.txt
/tmp/shortforge-sdk-check/bin/python -m unittest discover -s tests -v
npm ci
npm test
/tmp/shortforge-sdk-check/bin/python -m pip install -r worker/requirements.lock
SHORTFORGE_RUN_MEDIA_TESTS=1 /tmp/shortforge-sdk-check/bin/python -m unittest discover -s tests -v
OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 /tmp/shortforge-sdk-check/bin/python scripts/local_pipeline_check.py
```

FFmpeg/Tesseract/espeak locais são necessários para o teste completo, junto de
acesso ao modelo Whisper base/OCR ou cache verificado. O ensaio pode recusar
fala sintética; isso não deve ser contornado inventando legendas.

## Fontes oficiais conferidas

- https://vercel.com/docs/sandbox/sdk/python
- https://vercel.com/docs/sandbox/concepts/images
- https://vercel.com/docs/sandbox/pricing
- https://vercel.com/docs/vercel-blob/using-blob-sdk
- https://vercel.com/changelog/vercel-blob-now-supports-consistent-reads-on-private-storage
- https://vercel.com/changelog/vercel-blob-now-supports-ttls-for-automatic-deletion
- SDKs efetivamente instalados e assinaturas/código-fonte inspecionados localmente.
