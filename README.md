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


---

## Motor Vercel Sandbox (implementação experimental — desativada até configurar)

Foi adicionado código para executar o pipeline original do ShortForge em um
**Vercel Sandbox sob demanda**, sem colocar Whisper ou FFmpeg na Function HTTP.
Arquivos: \`api/sandbox_engine.py\`, \`api/policy.py\`, \`worker/runner.py\`,
\`api/download.js\`, \`api/index.py\`. O código só é ativado se todas as
credenciais exigidas estiverem presentes e a variável
\`SHORTFORGE_ENGINE=sandbox\` for definida.

**Ainda NÃO foi executado teste de vídeo real no Sandbox:** estes commits são
uma primeira implementação e testes automatizados sem cobrança, não uma
certificação de que o worker funciona no ambiente de produção. O vídeo de
validação continua sendo \`https://youtu.be/yWvnOWILFk0\`. É necessário medir
custos, confirmar acesso ao YouTube, pip/PyAV, instalação de ffmpeg/tesseract,
compatibilidade das duas Functions e armazenamento real.

### Limites protegidos no servidor

- Exatamente **5 cortes de 45 segundos**, em **720 × 1280**.
- Modelo de legendas **base**, não \`small\`.
- **2 vCPUs**, **4 GB RAM**, Sandbox limitado a **42 minutos**.
- **Apenas um processamento de cada vez**, bloqueado via Blob privado.
- **Máximo de 3 tarefas por mês** (configurável para menos, nunca para mais).
- Vídeo de origem entre 30 segundos e 6 horas.
- Autenticação Bearer com segredo único longo (mínimo 32 caracteres).
- \`/api/usage\` mostra contagem real de tarefas e estimativas conservadoras
  de consumo, mas **não equivale aos dados de faturamento** da Vercel.
- Depois de 24 horas, a API não retorna resultados expirados e o download
  assinado é recusado. O cron diário remove os blobs fisicamente; portanto,
  a exclusão definitiva pode demorar **24 a 48 horas após a geração**, não
  ocorre necessariamente no segundo exato em que completa 24 horas.
- Arquivos privados no Vercel Blob, links de download válidos por cinco minutos.
  Não publicar tokens privados em HTML/JS nem no GitHub.
- Callback autenticado tenta parar a VM ao concluir; limite de 42 minutos
  garante encerramento caso a chamada falhe.

### Variáveis de ambiente do projeto backend (somente Vercel)

Use \`.env.example\` como base. **Não coloque segredos reais no GitHub.**

1. Crie/conecte um **Vercel Blob com acesso private** ao projeto
   \`backend-short-clips\`. A conexão cria \`BLOB_READ_WRITE_TOKEN\`.
2. Cadastre \`SHORTFORGE_FRONTEND_ORIGIN=https://short-clips-tan.vercel.app\`.
3. Gere \`SHORTFORGE_PUBLIC_ACCESS_KEY\` e \`SHORTFORGE_WORKER_SECRET\`
   longos (mínimo 32 caracteres) e *diferentes*.
4. Defina \`SHORTFORGE_PUBLIC_API_URL=https://backend-short-clips.vercel.app\`.
5. Defina \`CRON_SECRET\` para proteger a limpeza automática.
6. Quando a implantação funcionar e a integração com Sandbox puder
   ser verificada, ative \`SHORTFORGE_ENGINE=sandbox\`.
7. Faça um novo deploy, acesse \`GET /api/health\` e depois teste o fluxo
   real com um vídeo permitido. \`ready:true\` significa **configurado**,
   não significa que cinco MP4s foram comprovadamente renderizados.

O frontend da branch \`main\` em
https://github.com/DevMurilo0/ShortClips agora envia para
\`https://backend-short-clips.vercel.app\`, aplica os limites do modo nuvem,
permite inserir a chave de acesso em sessão, solicita links temporários ao
\`GET /api/download\` e exibe consumo estimado em um painel.

**Atenção aos custos:** o Hobby tem franquias compartilhadas por equipe. O
limite de três processamentos é uma reserva conservadora, não impede que outros
projetos da equipe consumam CPU e armazenamento. Conferir os recursos reais
em *Vercel Dashboard → Usage* antes de iniciar qualquer vídeo.

### Testes que não consomem recursos

\`\`\`bash
python -m unittest discover -s tests -v
python -m py_compile api/index.py api/policy.py api/sandbox_engine.py worker/runner.py
node --check api/download.js
\`\`\`

O pipeline depende de APIs, hardware e permissões na conta. **A aprovação
destes testes não substitui teste de integração real** com Sandbox e Blob.
