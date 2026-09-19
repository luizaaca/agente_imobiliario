#!/usr/bin/env python3
"""Utilitário para gerar hashes bcrypt de senhas para o credentials.yaml."""

import getpass

from streamlit_authenticator.utilities.hasher import Hasher


def main():
    password = getpass.getpass("Digite a senha: ")
    if not password:
        print("Senha vazia. Abortado.")
        return
    print(f"Hash bcrypt: {Hasher.hash(password)}")
    print("Cole este hash no campo 'password' do config/credentials.yaml")


if __name__ == "__main__":
    main()
