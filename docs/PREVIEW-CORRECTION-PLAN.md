# Candidato de correção — não publicado

O único Preview autorizado está READY e passou em 32 verificações HTTP e na
consulta real do frontend, com motor desligado. Depois foram encontradas duas
falhas por inspeção/prova local, corrigidas e cobertas por testes:

1. Credenciais não ASCII provocavam TypeError na comparação HMAC. Agora retornam
   401 em usuário, cron e callback, sem depender do estado do motor.
2. Limpeza de retenção dependia de motor ativo. Agora usa seu próprio segredo e
   validação de namespace, inclusive enquanto a geração está pausada.

A correção 2 não ativa cron/schedules, não cria Sandbox e não oferece acesso de
limpeza pela chave do usuário. No perfil proposto não será definido CRON_SECRET.

65 testes Python aprovados (dois de mídia opcionais não repetidos), 14 Node e
build local do candidato aprovados. Artefato sem cron/schedules ou env files.

Para publicar, é indispensável uma SEGUNDA autorização de deploy, ainda não
concedida. Proposta de escopo:

- Um único novo Preview, `murilo15/backend-short-clips`, sem --prod.
- `SHORTFORGE_ENGINE=disabled`, somente nesse novo deployment.
- `SHORTFORGE_STORAGE_PREFIX=shortforge-preview/http-54d28e4b4113-authfix`, somente
  nesse novo deployment.
- `SHORTFORGE_PUBLIC_ACCESS_KEY` nova e exclusiva, somente nesse deployment.
- Nenhuma variável persistente, conexão Blob, proteção ou Production alterada.
- Nenhuma VM, vídeo, cron/schedule, push ou merge.
- Repetir os checks HTTP seguros, incluindo credenciais não ASCII; não simular
  um job completo. Verificar novamente Production ready=false.

Consumo esperado: mais um deploy prebuilt e algumas chamadas HTTP. O anterior
registrou contêiner de 9,804s, mínimo faturável de 60s e CPU faturável de 120s;
o custo oficial em US$ não está disponível. Nenhum custo Sandbox é previsto.

Sem autorização, manter o Preview atual inalterado e o candidato apenas local.
