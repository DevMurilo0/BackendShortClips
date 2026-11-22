# Homologação com processamento ativo em Preview

1. Aprovar um novo deployment e o orçamento de uma única VM. Antes de publicar, implementar e testar um perfil de homologação que aceite apenas uma mídia sintética previamente identificada no Blob privado, reserve uma tarefa e imponha até 10 minutos, 2 vCPUs e 4 GB. Exigir namespace próprio e bloquear URLs externas nesse perfil. Usar um Blob de teste dedicado se disponível.
2. Configurar credenciais exclusivas de teste para usuário e callback. Apontar o callback para a URL exata do Preview e validar a proteção Vercel com credencial de serviço autorizada. Confirmar o destino e o mecanismo de acesso antes de iniciar a VM.
3. Conectar o frontend de homologação ao Preview protegido. Enviar uma tarefa real e acompanhar a reserva, os estados persistentes, o callback autenticado e a destruição da VM. Conferir que outro pedido não cria uma segunda VM.
4. Solicitar MP4 e ZIP no navegador. Confirmar que a URL assinada funciona apenas no prazo previsto, que um arquivo fora da tarefa não recebe assinatura e que o MP4 é vertical em 720 × 1280, com áudio e legendas. Registrar estados e latência.
5. Pausar a admissão após o ensaio. Apagar apenas os objetos do namespace de teste e comprovar a remoção por HEAD. Homologar a retenção de até 24h separadamente, incluindo recuperação de falhas e alerta de atraso, conforme RETENTION-24H.md.

O lançamento depende da aprovação do fluxo completo e da retenção física. Qualquer ensaio adicional com VM precisa de autorização de consumo.
