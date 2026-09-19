#!/usr/bin/env python3
"""Utilitário para gerar hashes bcrypt de senhas para o credentials.yaml."""

import streamlit_authenticator as stauth


def main():
    password = input("Digite a senha: ")
    hashed = stauth.Hasher([password]).generate()[0]
    print(f"Hash bcrypt: {hashed}")
    print("Cole este hash no campo 'password' do config/credentials.yaml")


if __name__ == "__main__":
    main()
