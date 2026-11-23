# ShortForge — backend

API Python leve em Vercel Functions, worker de vídeo em Vercel Sandbox e
artefatos em Vercel Blob **privado**. O motor permanece desativado por padrão.
O ensaio real isolado Sandbox/Blob passou; a aplicação ainda não está liberada.
O Preview HTTP sem processamento passou em 32 verificações e no fluxo de
indisponibilidade do frontend real. Correções posteriores ainda estão locais.
Falta homologar processamento/Callback/downloads ativos e retenção em Preview.

Veja [o ensaio real](docs/CLOUD-INTEGRATION.md) e a
[proposta de retenção em 24h](docs/RETENTION-24H.md). Leia [o relatório de validação](docs/VALIDATION.md) para resultados, limitações,
consumo estimado e passos pendentes. Veja [o contrato da API](docs/API.md) para
integração e [a preparação de release](docs/RELEASE.md) antes de publicar.

```text
Frontend → API autenticada → mutex/quota/estado no Blob privado
                              ↓
                         Sandbox efêmero
                   seleção / OCR / Whisper / FFmpeg
                              ↓
                         MP4 + ZIP privados
Frontend ← estado e endpoint de autorização → URL temporária de um arquivo
```

Limites no backend: até 5 cortes de 30–45s, 720×1280, uma tarefa por vez,
máximo 3 reservas/mês, Sandbox com 2 vCPUs/4GB por até 42min. Acesso aos
resultados expira em 24h. Exclusão física ocorre por consulta/cron; o cron
Hobby diário ainda não oferece SLA de deleção em exatamente 24h.

Autenticação single-owner: Bearer longo informado pelo operador no frontend,
segredo separado para callback, `CRON_SECRET` para limpeza. Não colocar chaves
em HTML, variáveis públicas de build, URL ou logs. `.env.local` e `.vercel/`
são confidenciais. `.env.example` é somente uma referência sem credenciais.

```bash
python -m venv /tmp/shortforge-sdk-check
/tmp/shortforge-sdk-check/bin/python -m pip install -r requirements.txt
/tmp/shortforge-sdk-check/bin/python -m unittest discover -s tests -v
npm ci
npm test
```

As dependências pesadas ficam em `worker/requirements.lock`, não na Function.
`worker/Dockerfile` prepara uma imagem VCR para evitar instalar tudo por vídeo;
ela precisa ser construída e homologada antes de configurar sua referência.

`scripts/local_pipeline_check.py` valida mídia sintética local. O teste
`scripts/cloud_smoke.py --execute` consome infraestrutura e só deve ser
executado após autorização; sem o parâmetro não faz operações remotas.
Não habilitar `SHORTFORGE_ENGINE=sandbox` em Production sem aprovação explícita.

## Executar no computador, sem Vercel

Neste checkout, com `../ShortClips_Cloud` na branch `feat/local-dev-integration`:

```bash
./start-local.sh
# ou: ./start-local.sh --background
```

Abra http://localhost:5173. Health da API: http://localhost:8000/api/health.
As URLs reais são impressas se uma porta estiver ocupada. Encerre com `Ctrl+C`
no modo foreground ou `./stop-local.sh` a partir deste checkout.
`SHORTFORGE_FRONTEND_DIR` permite selecionar outro diretório do frontend.

A API local reutiliza `ShortClips_Cloud/app.py` e seu pipeline Python existente;
as Functions cloud deste repositório não são iniciadas. O proxy local autentica
as chamadas à API com chave somente em memória; o navegador usa `/api/...` e
`/downloads/...` na origem do frontend. A API e a interface escutam apenas em
loopback. Nenhum Sandbox, Blob ou `.env` é utilizado pelo modo local.

Comece com um vídeo individual HTTPS autorizado de 30–120s, com fala, para gerar
um Short de 30s em 720p. Confirme os direitos na interface. Os resultados são
salvos em `../ShortClips_Cloud/resultados-local/`, sem alterar os anteriores.
O modo local aceita até cinco cortes, mas o ensaio inicial deve ser pequeno.
Whisper base CPU/int8 e OCR português foram carregados/verificados; desempenho e
qualidade de um vídeo autorizado ainda dependem de teste real.

Verificações sem iniciar processamento:

```bash
python scripts/local_http_check.py
../ShortForge_Local/.venv/bin/python scripts/local_browser_check.py
```

O segundo comando utiliza Playwright/Chromium já instalados no ambiente existente.
Os testes rejeitam fontes inválidas sem baixar vídeos. Não criam tarefas falsas.
Resultados e limites desta rodada: [local-development-validation.json](docs/local-development-validation.json).
Geração, legendas, playback e downloads de MP4/ZIP reais continuam pendentes até
fornecer uma fonte autorizada; testes unitários não comprovam esse fluxo completo.
