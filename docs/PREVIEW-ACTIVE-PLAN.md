# Homologação com processamento ativo em Preview

1. Aprovar um novo deployment e o orçamento de uma única VM. Antes de publicar, implementar e testar um perfil de homologação que aceite apenas uma mídia sintética previamente identificada no Blob privado, reserve uma tarefa e imponha até 10 minutos, 2 vCPUs e 4 GB. Exigir namespace próprio e bloquear URLs externas nesse perfil. Usar um Blob de teste dedicado se disponível.
2. Configurar credenciais exclusivas de teste para usuário e callback. Apontar o callback para a URL exata do Preview e validar a proteção Vercel com credencial de serviço autorizada. Confirmar o destino e o mecanismo de acesso antes de iniciar a VM.
3. Conectar o frontend de homologação ao Preview protegido. Enviar uma tarefa real e acompanhar a reserva, os estados persistentes, o callback autenticado e a destruição da VM. Conferir que outro pedido não cria uma segunda VM.
4. Solicitar MP4 e ZIP no navegador. Confirmar que a URL assinada funciona apenas no prazo previsto, que um arquivo fora da tarefa não recebe assinatura e que o MP4 é vertical em 720 × 1280, com áudio e legendas. Registrar estados e latência.
5. Pausar a admissão após o ensaio. Apagar apenas os objetos do namespace de teste e comprovar a remoção por HEAD. Homologar a retenção de até 24h separadamente, incluindo recuperação de falhas e alerta de atraso, conforme RETENTION-24H.md.

O lançamento depende da aprovação do fluxo completo e da retenção física. Qualquer ensaio adicional com VM precisa de autorização de consumo.

## Preparação de código (sem deploy)

A branch `feat/preview-active-smoke-prep` acrescenta um perfil opt-in para uma única fonte sintética privada. Sua ativação exige o *mesmo deployment Preview* nas variáveis `SHORTFORGE_ENGINE=sandbox`, `SHORTFORGE_PREVIEW_SYNTHETIC_ONLY=1`, `SHORTFORGE_PREVIEW_TEST_BLOB=<namespace>/integration/<32-hex>/input.mp4`, `SHORTFORGE_STORAGE_PREFIX=<namespace>`, `SHORTFORGE_PUBLIC_API_URL=<URL exata de Preview>` e `SHORTFORGE_VERCEL_PROTECTION_BYPASS`, além de secrets de usuário/worker, Blob RW e frontend origin. Não configurar estas variáveis até autorização do novo deployment e da VM.

O pedido de ensaio deve enviar a URL sentinela `https://youtu.be/00000000000` com `count=1`, `length=30`, `resolution=720` e `manual_box=[0,0,50,80]`. A mídia real virá do Blob privado do operador, não do URL sentinela. O create-only `integration/once.json` bloqueia um segundo trabalho no mesmo namespace e continua existindo após a limpeza; use outro namespace em caso de nova autorização.

Um bypass de proteção deve ser gerado/administrado apenas pela Vercel; sem ele o callback em Preview protegido não deve iniciar o ensaio. A função HTTP de download exige Bearer próprio; não reutilizar o bypass no JavaScript estático. O worker não segue redirects ao enviar segredos e verifica um recibo JSON com o ID correto.

**Pendências:** executar testes novos em CI, confirmar se o SDK do Blob fornece URL assinada reproduzível no navegador, configurar um Preview isolado com aprovação específica e homologar execução de ponta a ponta. Nenhuma dessas ações está comprovada por este commit de preparação.
