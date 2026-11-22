# Homologação real do Preview HTTP — 22/11/2026

**32 verificações remotas aprovadas; correções posteriores aguardam publicação.** Um único deployment, sem segunda
publicação, Sandbox, vídeo, agendamento, push, merge ou deploy Production.

- URL: https://backend-short-clips-b4j9xdw78-murilo15.vercel.app
- Health: https://backend-short-clips-b4j9xdw78-murilo15.vercel.app/api/health
- Deployment: `dpl_Aunh8DQ5HgnYcJAiqxMEHMiCEfft`, READY, target Preview.
- Projeto conferido pela API: `prj_6q8UJw3x8PLQzdxAOMdnovAwqT1P`,
  `murilo15/backend-short-clips`.
- Fonte do código HTTP: commit local `a3e6841`; cópia isolada com cron/schedules
  removidos e artefato prebuilt. O cron do vercel.json normal não foi publicado
  nesse Preview. Arquivos de ambiente e dependências pesadas não entraram.

## Configuração e proteção

Apenas `SHORTFORGE_ENGINE`, `SHORTFORGE_STORAGE_PREFIX` e
`SHORTFORGE_PUBLIC_ACCESS_KEY` foram passadas com `vercel deploy --env NOME`,
com os valores herdados do ambiente do processo controlador, não na linha de
comando. A chave foi gerada exclusivamente para este teste, guardada em arquivo
local ignorado com permissão 0600, e não aparece nos logs ou relatórios.

Essas variáveis pertencem apenas ao deployment. Os snapshots de variáveis
persistentes do projeto, antes/depois, são iguais em Production e Preview;
metadados id/type/target/createdAt/updatedAt/gitBranch também foram comparados.
Nenhum comando env add/update/remove foi executado. As conexões Blob permaneceram
intactas. O namespace enviado foi `shortforge-preview/http-54d28e4b4113`.

O Preview continua protegido por Vercel Authentication. Uma requisição anônima
recebeu 302 para autenticação; a credencial OIDC Development existente permitiu
os testes. O header Trusted Sources foi limitado à origem exata desse Preview,
sem modificar regras, criar bypass persistente ou enviar token ao frontend.
A URL pode solicitar login Vercel ao ser aberta por uma pessoa.

## Testes reais HTTP

**32 verificações, 32 aprovadas, zero reprovadas.**

| Grupo | Comportamento observado |
|---|---|
| Health Python e rewrite | 200; mode=disabled; ready=false; no-store |
| Chave ausente/incorreta | 401 em jobs e download |
| Chave correta, motor desligado | 503 em jobs, status, usage, cancel/retry e download |
| CORS permitido | Origem do frontend aceita; OPTIONS 204 |
| CORS não permitido | Preflight e rotas privadas recusados com 403; health público sem ACAO |
| Cleanup/callback | 401 sem suas credenciais próprias; chave do usuário não autoriza limpeza |
| PUT/PATCH/DELETE | JSON 405 e Allow correto |
| HEAD | 405, sem corpo |
| Arquivos privados/helper Python | /.env.local, /.vercel/project.json e módulo auxiliar não expostos (404) |
| Rota inexistente | 404 |

Os 503 são o comportamento esperado e não representam falha de renderização:
**nenhuma renderização foi tentada**. A autenticação é verificada antes da
indisponibilidade. Os caminhos de storage nunca são alcançados nesse perfil.

## Frontend real

Chromium headless abriu o frontend publicado em
https://short-clips-tan.vercel.app e informou a URL do Preview pelo formulário.
A consulta CORS real `/api/health` retornou 200. A interface apresentou:

> Conexão não estabelecida: O servidor existe, mas seu worker de vídeos ainda não está configurado.

O botão de geração ficou desativado. Não houve POST de tarefa, página falsa de
sucesso ou vídeos simulados. Não houve pageerror. Nenhuma configuração persistente
ou deployment do frontend foi alterado. O acesso à proteção foi feito pelo
controlador de teste, fora do JavaScript da aplicação.

Isso confirma o fluxo de indisponibilidade e CORS; não confirma ainda autenticação
com geração ativa, cinco Shorts, reprodução ou download real no navegador.

## Consumo observado

- CLI do único deploy: 16,33s.
- Metadados Vercel: contêiner de build 9,804s; timeToReady 5,041s.
- `timeForBilling=60000` e `cpuTimeForBilling=120000` nos metadados de build:
  mínimo faturável de 60s e CPU faturável de 120s. São métricas de build,
  **não de Vercel Sandbox**. O prebuilt ainda passou por preparação da plataforma.
- 35 registros de requests retornados pela Vercel no instante da consulta, todos
  deste deployment: incluem bateria HTTP, probes e consulta do navegador.
  Consulta completa, sem paginação pendente ou intervalos excluídos.
- Consulta de logs runtime error/fatal: zero registros na janela consultada.
- Nenhum Sandbox novo; zero processamento e zero operações Blob nesta etapa.
- Não foi obtida fatura em US$, nem CPU/pico de memória das Functions por chamada.
  Não tratar esta execução como custo total zero.

Os status 401/403/405/503 registrados são testes negativos esperados. A distribuição
completa e os timestamps estão nos artefatos abaixo.

## Achados posteriores e correções ainda locais

Após as 32 verificações, uma prova local contra a fonte publicada demonstrou
`TypeError` ao comparar um Bearer não ASCII (exemplo de teste: `é`). O resultado
esperado é 401. A prova não foi enviada ao Preview remoto; não foi fabricado um
500 remoto no relatório. A correção local compara bytes UTF-8 em tempo constante
para autenticação de usuário, cron e worker. Foram adicionados três testes HTTP
locais, todos retornando 401 para credenciais inválidas não ASCII.

A revisão da retenção também encontrou uma dependência indevida: cleanup
exigia motor ativo. Isso impediria a limpeza de resultados depois de pausar a
geração. Corrigido localmente: cleanup continua exigindo seu segredo próprio e
namespace correto, mas independe da disponibilidade do processamento. Isso não
cria um scheduler nem autoriza a chave de usuário a apagar arquivos. O perfil
publicado não tem CRON_SECRET de Preview; esse caminho continua bloqueado nele.

Validação posterior: **65 testes Python aprovados, dois testes opcionais de
mídia não repetidos**, 14 Node aprovados e candidato corrigido construído
localmente sem cron/schedules. A mídia não mudou e já foi validada anteriormente.

**Essas correções não estão no Preview publicado.** Um segundo deploy exige
nova autorização, conforme a condição 10 do usuário. Não houve segunda tentativa.

## Production e pendências

Production permaneceu com health 200, mode=gateway, ready=false. O preset Python,
Node 26, raiz e configurações visíveis do projeto permaneceram como antes.
Nenhuma variável persistente, proteção, domínio ou branch remota foi modificada.

Antes de liberar:

1. Autorizar separadamente uma nova homologação com processamento **somente em
   Preview**. Antes de habilitar, impor uma tarefa e deadline de até dez minutos;
   o motor normal ainda tem limite de 42min. Preparar entrada sintética privada
   pelo operador: a API pública atual aceita apenas URLs YouTube e não deve ser
   aberta a URLs/paths arbitrários para facilitar o teste.
2. Validar API autenticada → quota/mutex → Sandbox → worker → estado → callback
   → links assinados → frontend → MP4/ZIP, incluindo erros e timeout/cancelamento.
   O teste anterior de worker/Blob direto passou, mas não cobre esse caminho HTTP.
3. Homologar o frontend com processamento ativo; publicar suas alterações locais
   de downloads somente com autorização. O frontend atual continua apontando
   originalmente para Production e recusa um backend indisponível corretamente.
4. Resolver retenção física: corte antecipado, índice pendente, retries/recibos e
   monitoramento; testar scheduler real com autorização. Nenhum schedule está
   habilitado aqui. TTL Blob em dias não garante exclusão em até 24h.
5. Homologar detecção automática de facecam, cinco cortes e uma fonte YouTube
   autorizada em etapa posterior; revisar autenticação single-owner antes de
   abrir para múltiplos usuários. Só então decidir liberação pública.

## Artefatos sem segredos

- [Resultado do deployment e consumo](preview-deployment-result.json)
- [32 verificações HTTP](preview-http-results.json)
- [Frontend real](preview-frontend-results.json)
- [Comparação de ambientes](preview-environment-verification.json)
- [Proposta de retenção](RETENTION-24H.md)

Dados brutos de controle e a chave do ensaio ficam em `.vercel/`, ignorada por
Git e excluída do pacote. Não anexar esses arquivos a relatórios ou publicações.
