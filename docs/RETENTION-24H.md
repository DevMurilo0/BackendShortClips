# Proposta para exclusão física em até 24 horas

## Conclusão

A limpeza diária atual não atende ao requisito. A proposta preferida é começar
exclusão em **22h** e executar a limpeza a cada **15 minutos**, com confirmação
por HEAD, tentativas seguintes e monitoramento antes do teto de 24h.

Há uma alternativa nativa que não foi considerada no primeiro levantamento:
**Vercel Schedules está em beta e permite frequência de 15 minutos no Hobby**.
O Cron legado continua limitado a uma vez por dia. Não é necessário presumir
upgrade Pro apenas para experimentar essa cadência.

Nenhum schedule foi criado ou habilitado e nenhum deploy foi feito. A proposta
precisa de homologação e autorização antes de ativar consumo recorrente.

## Arquitetura proposta

1. `SHORTFORGE_DELETE_AFTER_HOURS=22`, somente no ambiente homologado. O código
   local já suporta esse corte antecipado. O default continua 24h; Production
   não teve nenhuma variável alterada. Retenção passa a ser de **até 24h**, com
   possível remoção após 22h; a interface deve comunicar isso claramente.
2. Schedule estático `*/15 * * * *` chama `GET /api/cleanup`, autenticado com
   `CRON_SECRET`. Não colocar o segredo no JSON. O endpoint Python existente
   mantém a validação do Bearer. Prévia exige namespace próprio, inclusive
   para cleanup, evitando tocar em resultados de Production.
3. O handler termina/destroi a VM, combina a listagem com os caminhos do manifesto,
   apaga os artefatos em lotes e confirma ausência por HEAD. Só então grava o
   tombstone com `deletion.verified`, `deleted_at`, quantidade e indicador de
   atraso frente às 24h. Quota e uso permanecem. Essa confirmação foi testada
   localmente com simulador; os mesmos métodos de Blob foram exercitados no
   smoke real para a exclusão dos quatro arquivos do ensaio.
4. Falha de delete/HEAD não é registrada como exclusão bem-sucedida. O estado
   continua elegível para nova tentativa. Um schedule por path **não possui
   retry automático**: a próxima ocorrência tenta novamente. Para retries
   duráveis por execução, usar alvo Queue ou um scheduler externo com retries.
5. Acrescentar índice pequeno de tarefas pendentes e apagar o índice após o
   recibo. Isso evita reler indefinidamente todos os tombstones a cada 15min.
   Esse índice e monitoramento ainda não foram implementados; são passos antes
   de considerar o mecanismo operacionalmente pronto.
6. Monitorar execução e backlog. Alerta antes de 23h; bloquear novas admissões
   se a limpeza estiver sem funcionamento ou a franquia de schedules perto do
   limite. Não basta esconder arquivos nem chamar `delete` sem verificar.

Configuração candidata, **fora de vercel.json ativo**:

```json
{
  "schedules": {
    "shortforge-retention": {
      "schedule": "*/15 * * * *",
      "timezone": "UTC",
      "jitter": 15,
      "path": "/api/cleanup",
      "requestMethod": "GET"
    }
  }
}
```

No Hobby, o intervalo é 15min e o jitter é também de 15min. Em operação normal,
considerando alinhamento e jitter, uma tarefa elegível em 22h deve ser recolhida
até aproximadamente **22h30min + duração da Function**. Há cerca de 90min para
recuperação antes de 24h. Isso é uma estimativa operacional, não um SLA contratual.

## Consumo previsto

- Um schedule de 15min: 96 execuções/dia; até 2.976 em mês de 31 dias.
- Hobby admite 5.000 execuções por período para **a equipe inteira**, incluindo
  execuções manuais e outros projetos. Não deixar um segundo schedule de Preview
  funcionando o mês inteiro: os dois podem ultrapassar a franquia.
- Functions e operações Blob continuam sujeitos a consumo. Listagem vazia já
  custa uma operação; não existe promessa de custo zero. Com um índice, o custo
  basal é ~2.976 listagens/mês mais operações das poucas tarefas elegíveis.
- Preview nasce com schedules estáticos inativos. Para homologar, habilitar
  somente por uma janela curta, com desativação programada (`activeUntil`) e
  remoção do schedule ao finalizar. Isso requer autorização separada.

## Garantia e limite do provedor

A documentação permite entregas atrasadas e ocorrências puladas. Um alvo path
não repete automaticamente uma Function que falha. Por isso, **Schedules + Blob
não permitem prometer um limite físico absoluto de 24h durante uma indisponibilidade
prolongada do provedor**. A margem, recibos, retries e alarmes permitem construir
um SLO verificável; não substituem uma garantia contratual de exclusão.

Se o requisito for absoluto mesmo durante falhas externas, precisamos de um
provedor/contrato que assuma esse prazo de deleção, ou aprovar retenção efetiva
mais curta e tolerância de indisponibilidade. Criptografia com eliminação de chave
não equivale a apagar o objeto físico e não deve ser apresentada como substituto.

O TTL nativo do Blob também não resolve: é contado em dias inteiros, aplicado
à meia-noite UTC e pode ficar pendente de deleção por mais um dia. Não usar
`ttlDays=1` como garantia de remoção em 24h.

## Alternativa sem depender do beta

QStash permite agendar uma chamada atrasada de 22h (limite Free de sete dias)
com retries e assinatura. A franquia anunciada é 1.000 mensagens/dia; três tarefas
mensais ficariam muito abaixo dela, além de uma reconciliação periódica. Continua
existindo custo de Function/Blob e dependência externa; assinatura e chave de
verificação devem ficar só no backend. Não foi provisionado nem instalado nenhum
serviço ou integração. Essa alternativa também exige aceite e teste reais.

## Critérios da homologação

- Clock controlado: não apagar antes de 22h; apagar/confirmar depois de 22h;
  default 24h preservado; configuração >24h rejeitada. Testes locais implementados.
- Falha parcial ou HEAD ainda presente: não emitir recibo de sucesso. Teste local
  implementado; falhas reais não foram injetadas em nova VM.
- Namespace Preview não pode ler, assinar ou limpar Production. Testes locais
  implementados para API Python e função JS.
- Após aprovação de Preview, testar scheduler autenticação, duas entregas
  duplicadas, retry de falha, recibo e desativação, com timestamps controlados de
  uma tarefa de teste isolada. Não é necessário esperar 22h para validar o corte;
  para validar atraso real do scheduler, precisa de uma janela temporária ativa.
- Ensaio de 24h e monitoramento contínuo antes de afirmar cumprimento do SLO.

## Fontes oficiais, verificadas em 22/11/2026

- https://vercel.com/docs/schedules/limits
- https://vercel.com/docs/schedules/concepts
- https://vercel.com/docs/schedules/handle-runs
- https://vercel.com/docs/schedules/configuration
- https://vercel.com/docs/cron-jobs/usage-and-pricing
- https://vercel.com/docs/vercel-blob/using-blob-sdk#expire-blobs-automatically
- https://upstash.com/docs/qstash/features/delay
- https://upstash.com/docs/qstash/features/retry
- https://upstash.com/pricing/qstash


## Verificação adicional antes do Preview HTTP

O pacote do Preview HTTP será publicado sem `crons` ou `schedules`; a retenção
não será exercitada remotamente nesta etapa. Seu namespace não contém tarefas,
e os endpoints de geração, estado e download ficam indisponíveis após validar
as credenciais. Nenhuma chamada de Blob é necessária para essa homologação.

Para uma verificação posterior do prazo, medir `deleted_at - started_at` e
exigir `deletion.verified=true` e `past_24h_deadline=false`. Um relógio controlado
valida os cortes, mas não comprova pontualidade do scheduler: esta depende de
uma janela real autorizada. Se o objetivo for medido desde o término da tarefa
em vez da criação, isso precisa ser decidido antes de alterar o contrato atual,
que usa `started_at`. Contar desde a criação é conservador para o teto de 24h.

A margem de duas horas não é ilimitada: alinhamento de 15min, jitter de 15min
e uma Function de até 60s deixam aproximadamente 89min para falhas/recuperação
no pior alinhamento normal. A decisão operacional deve definir o limite de
indisponibilidade tolerado; acima dele, não há prova de cumprimento estrito em
Vercel Blob. O bloqueio de novas admissões evita aumentar o passivo, mas não
apaga magicamente arquivos de uma tarefa antiga durante indisponibilidade.
