"""
sondea_divisas.py — Averigua como llega la informacion de divisa y tipo de
cambio desde IB Gateway, para no escribir el conversor a ciegas.

Mismo espiritu que compara_posiciones.py: no nos fiamos de la documentacion,
le preguntamos al objeto real que campos trae y con que nombre exacto.

Ejecutar desde backend/ con el venv activado y el Gateway arrancado:
    python scripts/sondea_divisas.py

Usa clientId 98 a proposito: el 1 lo ocupa uvicorn y el 99 el otro script.
IB no admite dos conexiones con el mismo clientId.
"""

import os
from collections import defaultdict

from dotenv import load_dotenv
from ib_async import IB

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 77


def separador(titulo):
    print()
    print("=" * 72)
    print(titulo)
    print("=" * 72)


def main():
    ib = IB()
    print(f"Conectando a {HOST}:{PORT} (clientId={CLIENT_ID})...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"  ERROR: {e}")
        print("  Gateway arrancado? Puerto correcto? Prueba otro CLIENT_ID.")
        return

    cuenta = ib.managedAccounts()[0]
    print(f"  Conectado. Cuenta: {cuenta}")

    # El canal de cuenta tarda un momento en llenarse tras conectar.
    ib.sleep(3)

    # ------------------------------------------------------------------
    separador("1) accountValues() agrupados por divisa")
    # Es la fuente mas rica: trae cada magnitud repetida por divisa, mas
    # las etiquetas de tipo de cambio y de divisa base.
    valores = ib.accountValues(cuenta)
    print(f"Total de valores recibidos: {len(valores)}\n")

    por_divisa = defaultdict(list)
    for v in valores:
        por_divisa[v.currency or "(sin divisa)"].append(v)

    print("Divisas presentes:", ", ".join(sorted(por_divisa)))
    print()
    for divisa in sorted(por_divisa):
        print(f"  [{divisa}] -> {len(por_divisa[divisa])} etiquetas")

    # ------------------------------------------------------------------
    separador("2) Etiquetas candidatas a tipo de cambio / divisa base")
    # Buscamos por subcadena para no depender del nombre exacto.
    claves = ("exchangerate", "currency", "basecurrency", "cashbalance",
              "netliquidation", "totalcash")
    vistos = set()
    for v in valores:
        etiqueta = v.tag.lower()
        if any(c in etiqueta for c in claves):
            firma = (v.tag, v.currency)
            if firma in vistos:
                continue
            vistos.add(firma)
            print(f"  tag={v.tag!r:28} currency={v.currency!r:8} value={v.value!r}")

    # ------------------------------------------------------------------
    separador("3) accountSummary(): que devuelve el metodo que YA usamos")
    # Este es el que alimenta hoy account_values_to_summary. Interesa ver
    # si por si solo ya trae ExchangeRate o si hay que ir a accountValues.
    resumen = ib.accountSummary(cuenta)
    print(f"Total de filas: {len(resumen)}\n")
    divisas_resumen = sorted({s.currency for s in resumen if s.currency})
    print("Divisas que aparecen en accountSummary:", divisas_resumen or "(ninguna)")
    print()
    for s in resumen:
        if s.tag in ("NetLiquidation", "TotalCashValue", "AvailableFunds",
                     "BuyingPower", "ExchangeRate"):
            print(f"  tag={s.tag!r:20} currency={s.currency!r:8} value={s.value!r}")

    # ------------------------------------------------------------------
    separador("4) Divisas de las posiciones abiertas")
    cartera = ib.portfolio(cuenta)
    esperado = 0
    while not cartera and esperado < 10:
        ib.sleep(2)
        esperado += 2
        cartera = ib.portfolio(cuenta)

    for item in cartera:
        c = item.contract
        print(f"  {c.symbol:8} divisa={c.currency:5} "
              f"marketValue={item.marketValue!r:>14} "
              f"marketPrice={item.marketPrice!r}")

    # ------------------------------------------------------------------
    separador("5) Conclusion: lo que necesito saber")
    print("Pegame la salida COMPLETA. Lo que busco es:")
    print("  a) si existe una etiqueta de tipo de cambio y como se llama")
    print("  b) cual es la divisa base de la cuenta y de que campo se saca")
    print("  c) si accountSummary basta o hay que pasar a accountValues")
    print()
    print("Comprobacion util que puedes hacer tu mismo: multiplica el")
    print("marketValue total en USD por el tipo de cambio que salga arriba")
    print("y mira si se parece a la parte en EUR del valor liquidativo.")

    ib.disconnect()
    print("\nListo.")


if __name__ == "__main__":
    main()
