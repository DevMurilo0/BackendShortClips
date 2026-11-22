# Ensaio real autorizado — ShortForge

Executado em **22/11/2026, 18:56:10–18:58:21 UTC**. Uma única VM, nenhuma
repetição paga, nenhum deploy/push/merge ou alteração de variáveis de Production.
Autorização: até dez minutos, 2 vCPUs/4 GB, teto estimado US$0,057 de computação.
Foi usado cap mais conservador de **540s** e referência máxima de US$0,05112.

## Resultado real

**Integração Sandbox → worker → Blob privado → recuperação → exclusão aprovada.**

- Projeto retornado pelo SDK: `prj_6q8UJw3x8PLQzdxAOMdnovAwqT1P`, correspondente
  a `murilo15/backend-short-clips`; região iad1; 2 vCPUs, 4096 MB,
  persistent=false. VM `sf-test-41b3219dfac4949b984113b903cedd66`.
- Credencial: OIDC **Development**, com store privado conectado. A VM recebeu
  somente credenciais de storage necessárias por ambiente, não por argumentos.
  Não foi testada a injeção do token estático RW de uma Function Preview/Production.
- Uma rajada real de oito criações simultâneas do mesmo pathname teve **um
  vencedor**; sete conflitos reconhecidos pelo conteúdo da resposta foram
  mapeados pelo SDK Python como BlobError/400/bad_request. Isso confirma o caso
  observado; não substitui validação contínua de concorrência e falhas de rede.
- Fonte sintética gerada localmente por FFmpeg/espeak: 3.052.090 bytes. Nenhum
  acesso ao YouTube. Transferência de entrada por Blob privado real.
- Bootstrap instalou dependências Python e de sistema. O worker executou seleção
  por energia, OCR/análise de cena, **enquadramento manual**, Whisper base,
  legendas e FFmpeg reais. Detecção automática de facecam não foi exercitada.
- Estado final persistente: completed; processo do worker terminou com código 0.
- MP4 recuperado: **30,0s; 720×1280; áudio presente; 6.002.235 bytes**. ffprobe
  e decodificação completa com FFmpeg/xerror locais aprovados.
- SHA256 MP4: `6c44e900ba87d975f596afe70a18326e73f9aee2a8cb2b81f082c193caa1f806`.
- ZIP recuperado: 6.004.304 bytes; CRC íntegro; MP4 interno com o mesmo SHA256;
  contém `short_01.mp4`, `legendas/short_01.srt` e `relatorio.json`.
- O diretório temporário da tarefa no worker estava removido antes da parada.
- Sandbox parado, destruído e consulta posterior confirmou ausência. Nenhum
  snapshot persistente; remoção solicitada também para snapshots órfãos.
- Quatro blobs finais (entrada, estado, MP4 e ZIP) apagados; **zero restantes**
  no prefixo do ensaio; **quatro HEADs retornaram 404**. O mutex descartável já
  havia sido removido após seu teste. Só o prefixo deste UUID foi apagado.
- Production antes e depois: health 200, mode=gateway, ready=false.

## Consumo observado e estimado

| Métrica | Resultado |
|---|---|
| Preparação Python | 20,30s |
| Preparação do sistema + download de entrada | 23,15s no worker |
| Pipeline concluído | 46,93s após início do worker |
| Estado final salvo | 50,90s após início do worker |
| CPU do worker + filhos | 42,4s |
| Parada confirmada | 78,92s desde solicitação de criação |
| Artefatos MP4+ZIP | 12.006.539 bytes |
| Dados conhecidos armazenados simultaneamente | ~15,06 MB + pequeno JSON |
| Limite superior estimado de computação | **US$0,008439** |
| Fatura oficial / pico de memória | Não obtidos |

A CPU medida pelo worker **não inclui a instalação Python anterior ao runner**
nem toda a CPU da VM. A estimativa superior assume as duas CPUs ativas durante
os 78,92s e memória arredondada para dois minutos: CPU × US$0,128/h + memória ×
US$0,0212/GB-h. Não foi apresentada como fatura. Operações/transferência Blob
são adicionais; não há medição oficial desses custos nesta rodada.

A entidade Sandbox foi removida ao fim da validação local/recuperação dos
artefatos, 118,36s após a solicitação de criação. Esse intervalo inclui tempo
**após a parada** e não representa duração de VM alocada. O prazo remoto de
540s protege contra abandono do controlador, mas não foi necessário esperar
um timeout real para este ensaio.

## Logs relevantes

| UTC | Etapa |
|---|---|
| 18:56:12 | Mutex real: um vencedor |
| 18:56:19 | Sandbox criado |
| 18:56:40 | Dependências Python disponíveis |
| 18:56:42 | Entrada privada baixada |
| 18:57:04 | Dependências do sistema disponíveis |
| 18:57:28 | Pipeline terminou |
| 18:57:31 | Estado final salvo; temporários removidos |
| 18:58:17 | MP4/ZIP recuperados e validados |
| 18:58:21 | Exclusão da VM e dos blobs confirmada |

Fontes de evidência: [relatório JSON](cloud-smoke-result.json) e
[eventos sanitizados](cloud-smoke-events.jsonl). Não contêm tokens, ambientes
completos, URLs assinadas ou dumps de processos.

## Problemas e correções locais

- Uploads agora respeitam o cache mínimo documentado de 60s. Estado continua
  lido com `cache=0`. Ajuste preventivo antes da tentativa; não houve tentativa
  extra para contornar falha de upload.
- Durante o teste, a etapa local chegou a completed enquanto o estado global
  continuava running durante upload. Estado final foi publicado corretamente,
  mas o rótulo podia confundir a UI. Corrigido **depois do teste**, localmente:
  uploading e progresso <100 até os uploads terminarem. Testes de regressão.
- O motor normal agora faz stop + destroy, inclusive tentativa de destroy se
  stop falhar. O harness já confirmou stop/destroy reais; a mudança no motor
  normal foi testada com mocks, sem criar outra VM.
- Reforçado harness contra criação com resultado ambíguo, falha de stop,
  validação do envelope, confirmação de limpeza e diagnóstico sem segredos.
- Preview exige namespace separado; API, callback, cleanup e assinatura recusam
  namespace de Production. Cobertura local, sem publicação de Preview.
- Preparado corte antecipado opt-in da retenção e recibos por HEAD. Default e
  variáveis remotas preservados. Ainda depende de scheduler/monitoramento
  homologados; ver [proposta de retenção](RETENTION-24H.md).

## O que não foi validado neste ensaio

Frontend/API HTTP em Preview, callback autenticado real, assinatura/download via
Function Node, injeção estática RW na VM por uma Function, cancelamento/timeout
real, cinco cortes, vídeos longos, detecção automática de rosto ou YouTube.
Os caminhos de falha e isolamento foram testados localmente com simuladores.
Não repetir uma execução paga sem nova autorização.
