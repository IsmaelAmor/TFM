"""
compara_posiciones.py — Compara ib.positions() con ib.portfolio().

Objetivo: ver con datos reales de DUN684545 qué campos ofrece cada fuente,
para decidir cuál sustenta el modelo Position de T24.

Ejecutar desde backend/ con el venv activado y el Gateway arrancado:
    python compara_posiciones.py

Usa clientId 99 a proposito: el 1 puede estar ocupado por uvicorn.
IB no admite dos conexiones con el mismo clientId.
"""

import os

from dotenv import load_dotenv
from ib_async import IB

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 99


def campos(obj, saltar=("contract",)):
    """Devuelve los atributos de datos de un objeto de ib_async.

    Sirve para no fiarse de la documentacion: preguntamos al objeto real
    que campos trae y con que nombre exacto.
    """
    salida = {}
    for nombre in dir(obj):
        if nombre.startswith("_") or nombre in saltar:
            continue
        valor = getattr(obj, nombre)
        if callable(valor):
            continue
        salida[nombre] = valor
    return salida


def main():
    ib = IB()
    print(f"Conectando a {HOST}:{PORT} (clientId={CLIENT_ID})...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"  ERROR: {e}")
        print("  ¿Gateway arrancado y logueado? ¿Puerto correcto?")
        print("  Si el error menciona el clientId, cambia CLIENT_ID por otro numero.")
        return

    cuentas = ib.managedAccounts()
    print(f"  Conectado. Cuentas: {cuentas}\n")

    # ------------------------------------------------------------------
    print("=" * 70)
    print("1) ib.positions()  — canal reqPositions (contable)")
    print("=" * 70)
    posiciones = ib.positions()
    print(f"Devuelve {len(posiciones)} elementos.\n")
    for p in posiciones:
        print(f"  {p.contract.symbol} ({p.contract.secType})")
        for k, v in sorted(campos(p).items()):
            print(f"      {k} = {v!r}")
        print()

    # ------------------------------------------------------------------
    print("=" * 70)
    print("2) ib.portfolio()  — canal reqAccountUpdates (valorado)")
    print("=" * 70)

    # El canal de cuenta tarda un momento en llenarse tras conectar.
    # Esperamos hasta 10s antes de dar por hecho que viene vacio.
    cartera = ib.portfolio()
    esperado = 0
    while not cartera and esperado < 10:
        ib.sleep(2)
        esperado += 2
        cartera = ib.portfolio()
    if esperado:
        print(f"(hubo que esperar {esperado}s a que llegaran los datos)\n")

    print(f"Devuelve {len(cartera)} elementos.\n")
    for item in cartera:
        print(f"  {item.contract.symbol} ({item.contract.secType})")
        for k, v in sorted(campos(item).items()):
            print(f"      {k} = {v!r}")
        print()

    # ------------------------------------------------------------------
    print("=" * 70)
    print("3) Conclusion")
    print("=" * 70)
    solo_en_portfolio = set()
    if posiciones and cartera:
        solo_en_portfolio = set(campos(cartera[0])) - set(campos(posiciones[0]))

    if solo_en_portfolio:
        print("Campos que SOLO da portfolio():")
        for c in sorted(solo_en_portfolio):
            print(f"  - {c}")
    elif not cartera:
        print("portfolio() vino vacio. Puede ser que el canal de cuenta no se")
        print("haya activado. Anotalo y me lo cuentas: cambia la decision.")
    else:
        print("Sin diferencias de campos (revisar la salida de arriba).")

    ib.disconnect()
    print("\nListo.")


if __name__ == "__main__":
    main()
