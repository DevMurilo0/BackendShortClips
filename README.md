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

1. Crie um repositório GitHub vazio denominado `BackendShortClips`, na conta `DevMurilo0`.
2. Envie o conteúdo **desta pasta na raiz** do repositório (não envie o ZIP dentro de outro projeto).
3. Na Vercel, crie projeto separado `backendshortclips` vinculado ao repositório `DevMurilo0/BackendShortClips`, com `Framework Preset: Other`.
4. Adicione as variáveis de `.env.example` usando **valores reais privados**, não os exemplos. Nunca publique segredos no repositório nem no `index.html`.
5. Confira `https://<dominio-do-backend>/api/health`.
6. No frontend ShortClips defina `SHORTFORGE_PUBLIC_API_URL=https://<dominio-do-backend>`, ou utilize o campo de conexão da interface.
7. Crie o **worker persistente real** e o armazenamento dos MP4/ZIP antes de considerar a aplicação funcional.

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
# BackendShortClips
