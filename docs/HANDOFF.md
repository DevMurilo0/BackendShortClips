# ShortForge — passagem de contexto (22/11/2026)

## Onde está o código

- Backend: `DevMurilo0/BackendShortClips`, branch de trabalho `fix/sandbox-pipeline-validation`.
- Frontend: `DevMurilo0/ShortClips`, branch `feat/smart-clips-vercel`.
- Esta preparação adicional é proposta na branch `feat/preview-active-smoke-prep`.
- Production: `https://backend-short-clips.vercel.app`, motor em gateway, `ready=false` no último teste relatado.
- Segundo Preview HTTP (somente leitura): `https://backend-short-clips-ipltw3gpb-murilo15.vercel.app` — `mode=disabled` no ensaio anterior.
- Projeto Vercel do backend: `murilo15/backend-short-clips`; Blob privado, namespaces por ambiente.

## O que foi validado pelo Codex

- 65 testes Python (2 opcionais de mídia não repetidos no último ciclo), 14 Node e 35 verificações HTTP reais no Preview desativado.
- Um ensaio real isolado Sandbox/Blob produziu MP4 720×1280 de 30 s com áudio, ZIP íntegro; VM e quatro objetos Blob foram removidos.
- Esses resultados são **históricos**; não equivalem a testes de ponta a ponta da API com Sandbox ativo.
- O Preview HTTP está protegido por Deployment Protection, que exige bypass autorizado para callback automatizado.
- Fonte: `docs/PREVIEW-AUTHFIX.md`, `docs/CLOUD-INTEGRATION.md`, `docs/PREVIEW-ACTIVE-PLAN.md`.

## Implementação preparada nesta branch

- Modo sintético opt-in **exclusivo de Preview** via `SHORTFORGE_PREVIEW_SYNTHETIC_ONLY=1` e `SHORTFORGE_PREVIEW_TEST_BLOB` apontando para um arquivo `<namespace>/integration/<32 hex>/input.mp4` já carregado no Blob privado.
- Quando o motor está ativo em Preview, a ausência desse perfil sintético e de bypass bloqueia a configuração (fail closed); não permite fallback para job YouTube de 42min.
- Exige exatamente 1 Short de 30 segundos, 720p, facecam manual, URL sentinela `https://youtu.be/00000000000`; **essa URL não será baixada**, pois a fonte é o Blob pré-configurado pelo operador.
- Reservar `<namespace>/integration/once.json` com create-only evita segundo ensaio pago no mesmo namespace. O Sandbox de teste recebe timeout de 10 minutos e os recursos normais de 2 vCPU / 4096 MB. Sem flags, o motor mantém o comportamento anterior.
- O worker valida o namespace da fonte sintética, evita redirecionar segredos de callback e reconhece confirmação HTTP real `{ok: true, id}`.
- Callback do Preview exige URL exata de deployment Vercel desta equipe + `SHORTFORGE_VERCEL_PROTECTION_BYPASS`, enviada somente pelo servidor ao worker como header. **Não incluir em frontend, URLs ou GitHub.**

## Próximas verificações e restrições

1. Testar a nova branch com `python -m unittest discover -s tests -v` e `npm test` em CI, sem credenciais reais.
2. Validar a assinatura do download privado no SDK real e tratamento de Deployment Protection no navegador.
3. Revisar variáveis **somente no novo deployment Preview** e inspecionar artefato/build; verificar Production inalterada. Não há nova autorização para deploy nem para executar VM.
4. Depois de autorização explícita, ensaio ativo com mídia sintética privada, callback, estados, download MP4/ZIP e limpeza por HEAD. Registrar custos e remover artefatos do namespace de teste.
5. Provar geração de cinco Shorts, detecção de facecam auto, seleção de trechos e fonte YouTube autorizada; evitar testes caros sem aceite.
6. Retenção física estrita de até 24 h ainda **não homologada**; `docs/RETENTION-24H.md` descreve proposta de corte em 22h, scheduler, recibos, monitoramento e falhas. Não ativar agendas até autorização.

**Segurança:** nunca inserir tokens ou `.env.local` em commits, logs, dados da UI ou URLs; não mudar Production, não ativar Schedules nem criar Sandbox nesta etapa. Branch de preparação não habilita engine por padrão.
