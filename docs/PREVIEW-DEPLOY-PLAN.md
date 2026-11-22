# Deploy Preview HTTP — histórico do plano aprovado

Projeto verificado por CLI: `murilo15/backend-short-clips`,
`prj_6q8UJw3x8PLQzdxAOMdnovAwqT1P`. Production respondeu ready=false.

Somente UM deploy Preview. Nenhum Sandbox, push, merge, promoção ou mudança
em Production. Pacote isolado terá `crons` e `schedules` removidos; nenhuma
configuração de agendamento será criada. O vercel.json normal do repositório
não será aplicado com seu cron diário a este Preview.

O ambiente Preview atualmente contém apenas as conexões Blob. Para autenticação
HTTP e namespace explícito são indispensáveis estas três variáveis, restritas
**ao novo deployment**, sem criar/editar as variáveis persistentes do projeto:

| Variável | Uso |
|---|---|
| SHORTFORGE_ENGINE | `disabled`: bloqueia Sandbox e também qualquer proxy externo |
| SHORTFORGE_STORAGE_PREFIX | `shortforge-preview/<id exclusivo>`: isolamento |
| SHORTFORGE_PUBLIC_ACCESS_KEY | chave nova privada exclusiva do teste HTTP |

Nenhuma variável Blob, de Production, WORKER_SECRET ou CRON_SECRET será editada.
A chave será gerada localmente e nunca será exibida nem enviada como argumento
literal de comando ou código-fonte. O método de envio será verificado com dry-run
antes da única chamada de deploy. Arquivos de credenciais ficam fora do pacote.

As três variáveis foram aprovadas explicitamente e o único deployment foi
executado. Resultado: PREVIEW-HTTP-VALIDATION.md. O restante deste arquivo
preserva o plano usado; nenhuma variável persistente foi editada.

Correções locais preparadas: modo disabled sempre ready=false e sem proxy;
autenticação avaliada antes de retornar indisponibilidade quando existe uma
chave; métodos não suportados respondem JSON 405. Download verifica autenticação
antes da indisponibilidade, sem ler Blob com engine disabled.

Testes remotos planejados: health, rotas reais Python/Node, preflight CORS,
origem recusada, chave ausente/incorreta, chave válida com HTTP 503, métodos,
cron/callback não autorizados, nenhuma tarefa iniciada e nenhum dado de Blob
acessado. Navegador com origem do frontend deve apresentar indisponibilidade,
sem simular geração. Protection deve permanecer como está; não criar bypass sem
avaliação/autorização se as credenciais existentes forem insuficientes.

Após a execução, confirmar Production ready=false, registrar URL/status, consumo
observável e falhas. Se falhar, corrigir e testar localmente; não fazer outro
deploy sem nova autorização.
