# Autenticação da UI

**Objetivo:** definir a estratégia de autenticação da interface Streamlit, protegendo dashboard, chat simulador e demais elementos visuais da POC.

---

## 1. Premissa

**Toda a aplicação Streamlit fica protegida por login.** Nenhum conteúdo — dashboard, chat simulador, QR code do Telegram — é acessível sem autenticação. A tela de login é o primeiro ponto de contato ao abrir a URL.

O Bot Telegram não é afetado — ele opera com identidade implícita via `chat_id`.

---

## 2. Ferramenta escolhida: `streamlit-authenticator`

| Aspecto | Detalhe |
|---|---|
| Biblioteca | [`streamlit-authenticator`](https://github.com/mkhorasani/Streamlit-Authenticator) |
| Versão | >=0.3 |
| Hash de senha | bcrypt |
| Sessão | Cookie HTTP com expiração configurável |
| Esforço | ~20 linhas de integração |

---

## 3. Configuração de credenciais

### Via arquivo YAML (recomendado para a POC)

```yaml
# config/credentials.yaml
credentials:
  usernames:
    admin:
      name: Administrador
      password: "$2b$12$..."   # hash bcrypt gerado pelo script abaixo
    corretor1:
      name: João Silva
      password: "$2b$12$..."

cookie:
  name: sdr_imobiliario_auth
  key: ${AUTH_COOKIE_KEY}       # variável de ambiente
  expiry_days: 7
```

### Script para gerar hash de senha

```python
# scripts/generate_password_hash.py
import streamlit_authenticator as stauth

password = input("Digite a senha: ")
hashed = stauth.Hasher([password]).generate()[0]
print(f"Hash bcrypt: {hashed}")
```

Uso:
```bash
python scripts/generate_password_hash.py
# Digite a senha: minha_senha_segura
# Hash bcrypt: $2b$12$abc123...
```

---

## 4. Integração no `app.py`

```python
# app.py
import os
import yaml
import streamlit as st
import streamlit_authenticator as stauth

# --- Autenticação (antes de qualquer conteúdo) ---

with open("config/credentials.yaml") as f:
    config = yaml.safe_load(f)

# Substituir a chave do cookie pela variável de ambiente
config["cookie"]["key"] = settings.AUTH_COOKIE_KEY
# Sem AUTH_COOKIE_KEY no ambiente, src/config.py sorteia uma chave por
# processo e registra alerta. Um default fixo aqui seria publico, e com ele
# qualquer um forjaria um cookie de admin sem passar pelo login.

authenticator = stauth.Authenticate(
    credentials=config["credentials"],
    cookie_name=config["cookie"]["name"],
    cookie_key=config["cookie"]["key"],
    cookie_expiry_days=config["cookie"]["expiry_days"],
)

name, authentication_status, username = authenticator.login()

if authentication_status is False:
    st.error("❌ Usuário ou senha incorretos.")
    st.stop()

if authentication_status is None:
    st.warning("🔒 Por favor, faça login para acessar o sistema.")
    st.stop()

# --- A partir daqui, o usuário está autenticado ---

# Sidebar com info do usuário e botão de logout
with st.sidebar:
    st.write(f"👤 **{name}**")
    authenticator.logout("Sair", "sidebar")

# Navegação entre abas (tudo protegido)
tab_chat, tab_dashboard = st.tabs(["💬 Chat Simulador", "📊 Dashboard"])

with tab_chat:
    # ... renderiza o chat
    pass

with tab_dashboard:
    # ... renderiza o dashboard do corretor
    pass
```

### Ponto-chave: `st.stop()`

O `st.stop()` é chamado antes de qualquer conteúdo quando o login falha ou não foi realizado. Isso **interrompe a execução do script** — nenhum widget, dado ou QR code é renderizado.

---

## 5. Proteção por componente

| Componente | Mecanismo |
|---|---|
| **Toda a UI Streamlit** | `st.stop()` bloqueia renderização se `authentication_status != True` |
| **Dashboard** | Renderizado apenas após autenticação bem-sucedida |
| **Chat Simulador** | Renderizado apenas após autenticação bem-sucedida |
| **QR Code Telegram** | Renderizado apenas após autenticação bem-sucedida |
| **Bot Telegram** | Independente — identidade via `chat_id` |
| **Banco de dados** | Acesso interno — não exposto via HTTP |

---

## 6. Variáveis de ambiente

```env
# Chave secreta que assina o cookie de sessão
# Gerar com: python -c "import secrets; print(secrets.token_urlsafe(48))"
AUTH_COOKIE_KEY=a1b2c3d4e5f6...
```

### Ausência da chave

`AUTH_COOKIE_KEY` **não tem valor padrão**: um default fixo no código seria público e permitiria forjar um cookie de sessão e entrar como administrador sem passar pelo login.

Quando a variável não vem do ambiente, `src/config.py` (`_resolver_chave_do_cookie`) sorteia uma chave com `secrets.token_urlsafe(48)` na inicialização do processo e sinaliza isso em `settings.AUTH_COOKIE_KEY_GERADA`. O aviso sai por dois canais:

1. **log**, para quem opera:
   `event=auth_cookie_key_gerada impacto=sessoes_caem_a_cada_restart_e_nao_funcionam_com_replicas`
2. **balão dispensável na UI**, uma vez por sessão (`src/ui/navegacao.py`), para quem está na tela entender por que pode ser deslogado sem motivo aparente.

A aplicação **funciona normalmente** assim. As duas limitações são:

| Limitação | Por quê |
|---|---|
| A sessão cai a cada reinício | A chave é sorteada de novo e os cookies emitidos antes deixam de validar |
| Não funciona com múltiplas réplicas | Cada processo assina com uma chave diferente; o usuário é deslogado ao cair numa réplica distinta da que autenticou |

Ou seja: aceitável para desenvolvimento e para a demonstração da POC, inadequado para qualquer deploy com mais de uma instância ou que precise de sessão estável.

---

## 7. Estrutura de diretórios adicionais

```text
agente_imobiliario/
├── config/
│   └── credentials.yaml       # Credenciais com hashes bcrypt
├── scripts/
│   └── generate_password_hash.py
└── ...
```

---

## 8. Considerações de segurança

- **Nunca commitar senhas em texto plano.** O arquivo `credentials.yaml` contém apenas hashes bcrypt.
- **`AUTH_COOKIE_KEY` deve ser única por ambiente.** Gerar com `secrets.token_urlsafe(48)`. Sem ela a aplicação sorteia uma por processo e avisa — ver seção 6.
- **HTTPS obrigatório em produção.** O cookie de sessão trafega pelo navegador — sem HTTPS, está vulnerável a interceptação. Railway, Render e Fly.io fornecem HTTPS automático.
- **`.env` no `.gitignore`.** Nunca versionar o arquivo com chaves reais.

---

## 9. Checklist de implementação

- [x] Instalar `streamlit-authenticator` e `pyyaml` no `requirements.txt`.
- [x] Criar `config/credentials.yaml` com pelo menos um usuário admin.
- [x] Criar `scripts/generate_password_hash.py`.
- [x] Integrar autenticação no início de `app.py` com `st.stop()`.
- [x] Adicionar `AUTH_COOKIE_KEY` ao `.env.example`.
- [x] Adicionar `config/credentials.yaml` ao `.gitignore` (ou manter com hashes apenas).
  > Mantido versionado, só com hashes bcrypt — é o que permite subir o projeto e logar sem passo extra.
- [x] Testar: abrir URL sem login → ver apenas tela de login.
- [x] Testar: login com credenciais corretas → acesso total.
- [x] Testar: refresh da página → sessão mantida pelo cookie.
