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
