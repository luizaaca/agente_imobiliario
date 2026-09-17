# ADR 0003 — Usar Telegram como canal real da POC

- **Status:** Aceito
- **Data:** 2026-09-16

## Contexto

A POC precisa demonstrar um canal real de mensageria com baixo custo, rápida configuração e boa experiência para demonstração.

O mercado imobiliário brasileiro usa majoritariamente WhatsApp, mas a integração oficial possui maior burocracia, custo e tempo de setup.

## Decisão

Usar **Telegram Bot API** como canal real de mensageria da POC, mantendo o chat Streamlit como ambiente de simulação e dashboard.

## Alternativas consideradas

### 1. WhatsApp Business API
- **Prós:** aderência maior ao mercado real.
- **Contras:** maior complexidade, custo e dependência de aprovação.

### 2. Apenas chat Streamlit
- **Prós:** simplicidade máxima.
- **Contras:** demonstração menos realista, sem experiência mobile autêntica.

## Consequências

### Positivas
- custo zero ou muito baixo;
- setup rápido;
- experiência real de mensageria para demo;
- integração simples com polling local.

### Negativas
- menor aderência ao canal dominante do mercado;
- necessidade de explicar a escolha no pitch.

## Impacto arquitetural

O canal Telegram é tratado como adaptador externo, sem contaminar a lógica de domínio. Isso facilita futura troca por WhatsApp.
