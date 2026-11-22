# Homologação em Preview — proposta aguardando autorização

O ensaio isolado real passou. **Não foi criado deploy Preview.** Nenhuma ação
abaixo está autorizada implicitamente pelo teste já concluído.

## Etapa 1: publicar Preview sem processamento

- Projeto: `murilo15/backend-short-clips`, branch/commit local revisado.
- Criar somente Preview, sem atribuir domínio Production ou promover deployment.
- `SHORTFORGE_ENGINE` continua desativado no Preview inicial e em Production.
  Assim nenhum teste HTTP inicia Sandbox.
- Usar `SHORTFORGE_STORAGE_PREFIX=shortforge-preview/homologation` no ambiente
  de homologação; nunca copiar o namespace de Production. O código agora recusa
  namespaces compartilhados em Preview, inclusive cleanup e assinatura.
- Chaves de teste próprias, geradas/armazenadas privadamente; não reutilizar chave
  do usuário/worker/cron de Production. Preservar conexões/token RW existentes.
- `.env.local`, `.vercel/`, relatórios, testes, modelos locais e dependências de
  mídia ficam fora do artefato. O build local confere essas exclusões.
- Sem schedules ativos na primeira publicação. O código não habilita nem cria
  schedules em runtime.
- Verificar health, roteamento Python/Node, CORS, indisponibilidade de geração,
  métodos e ausência de segredos nas respostas. Isso não valida ainda o fluxo
  autenticado completo porque o motor permanece desativado.

Consumo novo: build Preview e algumas Functions HTTP. Não haverá nova VM nessa
etapa. Como o usuário solicitou aprovação de Preview, só executar após aceite
explícito; ainda não foi medido um custo oficial de build/Functions.

## Etapa 2: nova homologação com processamento, se autorizada separadamente

- Nova autorização específica de computação antes de qualquer outra VM.
- Habilitar motor **somente no Preview isolado** por uma janela curta, com
  credenciais de teste e controles adicionais para limitar o ensaio a uma tarefa
  sintética e dez minutos. O motor normal ainda tem deadline de 42min; não
  habilitá-lo sem antes impor o envelope temporário de homologação.
- Validar requisição autenticada → API → quota/mutex → Sandbox → worker → Blob →
  estado → callback → URL assinada → navegador → MP4/ZIP. Não usar YouTube.
- Testar falhas de autenticação e pertencimento, cancelamento/timeout dentro do
  orçamento aprovado, limpeza, estado após reinício e isolamento de namespace.
- Desabilitar geração no Preview ao terminar e confirmar remoção dos artefatos.

## Etapa 3: retenção

Aprovar o perfil descrito em RETENTION-24H.md: exclusão iniciada em 22h,
Schedules Hobby de 15min com janela limitada em Preview, recibos, índice de
pendências e monitoramento. O código local suporta corte antecipado e confirmação
por HEAD; índice/monitoramento e validação de agendamento ainda faltam.

Ativar uma janela curta do schedule custa Functions/Blob e conta na franquia da
equipe. Precisa de aprovação distinta; nada foi provisionado/ativado. Não
prometer SLA absoluto de 24h sem definir tratamento de indisponibilidade do
provedor. TTL diário do Blob não garante esse prazo.

Production só pode ser habilitada após essa homologação e autorização explícita.
Push, merge e deploy Production continuam não autorizados.
