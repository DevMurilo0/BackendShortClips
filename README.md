# BackendShortClips

Backend Python **independente** do site ShortClips, preparado para deploy na Vercel.

## Arquitetura

```text
Site ShortClips na Vercel (HTML/JS)
    │ URL HTTPS + Bearer key
    ▼
BackendShortClips na Vercel (API Python, este repositório)
    │ segredo de serviço
    ▼
Worker persistente (Python + yt-dlp + OpenCV + Whisper + FFmpeg)
    │
    ▼
Armazenamento de MP4/ZIP (URLs autorizadas)
```

**O gateway Python não processa vídeos.** A Vercel Function executa pedidos curtos e consulta os estados. Renderizar vídeos longos requer um worker persistente, fila, banco de tarefas e armazenamento durável. Não se deve usar o filesystem de Vercel Functions como armazenamento permanente.

## O que funciona nesta etapa

- `GET /api/health`: retorna `ok: true` e `ready: false` enquanto não houver worker configurado.
- `POST /api/jobs`: encaminha um novo pedido ao worker quando todas as variáveis estiverem configuradas.
- `GET /api/jobs/latest` e `GET /api/jobs/<id>`: consultam estados.
- `POST /api/jobs/<id>/cancel` e `/retry`: encaminham comandos.
- `OPTIONS`: responde ao preflight CORS apenas para a origem permitida.
- Autenticação Bearer e segredo de comunicação com o worker.
- Sem worker, responde HTTP 503 (em vez de fingir geração).
- Downloads MP4/ZIP **ainda precisam ser implementados** via storage com URL assinada.

## Criar repositório e deploy

1. Repositório já criado: https://github.com/DevMurilo0/BackendShortClips (este repositório).
2. Na Vercel, crie o projeto `backendshortclips` vinculando **este GitHub**, com `Framework Preset: Other` e raiz `.`.
3. Adicione as variáveis de `.env.example` usando **valores reais privados**, não os exemplos. Nunca publique segredos no repositório nem no `index.html`.
4. Confira `https://<dominio-real-do-backend>/api/health`. Antes do worker, `ready: false` é esperado.
5. No projeto frontend [ShortClips](https://github.com/DevMurilo0/ShortClips), configure `SHORTFORGE_PUBLIC_API_URL=https://<dominio-real-do-backend>` na Vercel. Sua interface na branch `feat/smart-clips-vercel` já reconhece essa variável e a chave informada no formulário.
6. Defina `SHORTFORGE_FRONTEND_ORIGIN` no backend com a **origem exata do site publicado** (sem barra final), para liberar CORS.
7. Implemente um **worker real e armazenamento durável** de MP4/ZIP antes de habilitar geração. Este gateway não é um renderizador, e o site não deve anunciar Shorts prontos sem MP4 válido.

## Antes de tornar o processamento público

- Autenticação por usuário (a chave única é apenas um protótipo para uso pessoal), autorização por tarefa, limite de jobs, quotas e rate limiting.
- Worker com fila e estado persistente. Uma máquina Vercel Sandbox sob demanda pode ser avaliada, mas possui limites de execução e consumo e pode não ser gratuita em uso contínuo.
- HTTPS e URLs assinadas para downloads.
- Proteção de gastos e confirmação de custos antes de ativar recursos computacionais.

## Verificar código

```bash
python -m unittest discover -s tests -v
python -m py_compile api/index.py
```

Se `ready` for `false`, a API está disponível mas **não há produção de MP4s**. Isso é esperado até configurar o processamento separado.
