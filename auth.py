# -*- coding: utf-8 -*-
"""
Utilidades de autenticación.
Usa hashlib.pbkdf2_hmac (librería estándar de Python) para no depender de
paquetes externos como bcrypt, que a veces dan problemas al instalar en Windows.
"""
import hashlib
import os
import hmac

ITERACIONES = 260_000


def hash_password(password: str) -> str:
    sal = os.urandom(16)
    derivado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, ITERACIONES)
    return f"{sal.hex()}${derivado.hex()}"


def verificar_password(password: str, hash_guardado: str) -> bool:
    try:
        sal_hex, derivado_hex = hash_guardado.split("$")
        sal = bytes.fromhex(sal_hex)
        derivado_esperado = bytes.fromhex(derivado_hex)
        derivado_actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, ITERACIONES)
        return hmac.compare_digest(derivado_actual, derivado_esperado)
    except Exception:
        return False
