"""
sondea_instrumentos.py — Averigua que devuelven de verdad la busqueda de
instrumentos y la peticion de precio delayed, antes de escribir T33 y T34.

Mismo espiritu que compara_posiciones.py y sondea_divisas.py: no nos fiamos
de la documentacion, le preguntamos al objeto real que campos trae y con
que nombre exacto.

Ejecutar desde backend/ con el venv activado y el Gateway arrancado:
    python scripts/sondea_instrumentos.py

Usa clientId 76: el 1 lo ocupa uvicorn, el 77 sondea_divisas y el 99
compara_posiciones. IB no admite dos conexiones con el mismo clientId.
"""

import os

from dotenv import load_dotenv
from ib_async import IB, Stock

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 76

# Tres patrones a proposito: ticker exacto, nombre parcial de empresa y un
# ETF. El tercero importa porque IB clasifica SMH como STK igual que una
# accion, y hay que ver si algun campo permite distinguirlos.
PATRONES = ["AMZN", "Iberdrola", "SMH"]


def separador(titulo):
    print()
    print("=" * 72)
    print(titulo)
    print("=" * 72)


def campos(obj, saltar=()):
    """Atributos de datos de un objeto de ib_async, sin metodos."""
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
        print("  Gateway arrancado? Puerto correcto? Prueba otro CLIENT_ID.")
        return

    print(f"  Conectado. Cuenta: {ib.managedAccounts()}")

    # ------------------------------------------------------------------
    separador("1) reqMatchingSymbols(): la busqueda de T33")
    # Es el unico metodo de la API que acepta texto parcial y busca tanto
    # por ticker como por nombre de empresa. reqContractDetails exige el
    # simbolo exacto, asi que no sirve para un buscador.
    # Limite documentado: una peticion por segundo. Por eso el sleep.
    for patron in PATRONES:
        print(f"\n--- patron: {patron!r}")
        try:
            resultados = ib.reqMatchingSymbols(patron)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if not resultados:
            print("  Sin resultados.")
            ib.sleep(1.1)
            continue

        print(f"  {len(resultados)} resultados. Primeros 3 en detalle:\n")
        for desc in resultados[:3]:
            print("  ContractDescription:")
            for k, v in sorted(campos(desc, saltar=("contract",)).items()):
                print(f"      {k} = {v!r}")
            print("    .contract:")
            for k, v in sorted(campos(desc.contract).items()):
                if v not in ("", 0, [], None, False):
                    print(f"      {k} = {v!r}")
            print()

        # Resumen compacto del resto, para ver el ruido que devuelve.
        print("  Resto (compacto):")
        for desc in resultados[3:]:
            c = desc.contract
            print(f"      {c.symbol:12} {c.secType:6} {c.currency:5} "
                  f"{c.primaryExchange or '-':12} conId={c.conId}")

        ib.sleep(1.1)  # limite de una peticion por segundo

    # ------------------------------------------------------------------
    separador("2) reqContractDetails(): que anade sobre la busqueda")
    # Interesa saber si trae longName, industry y stockType. Si los trae,
    # son la diferencia entre un buscador que muestra 'AMZN' y uno que
    # muestra 'AMZN — Amazon.com Inc — Consumer, Retail'.
    detalles = ib.reqContractDetails(Stock("AMZN", "SMART", "USD"))
    print(f"Devuelve {len(detalles)} elementos.\n")
    if detalles:
        d = detalles[0]
        for k, v in sorted(campos(d, saltar=("contract",)).items()):
            if v not in ("", 0, [], None, False):
                print(f"  {k} = {v!r}")
        print("\n  .contract:")
        for k, v in sorted(campos(d.contract).items()):
            if v not in ("", 0, [], None, False):
                print(f"      {k} = {v!r}")

    # ------------------------------------------------------------------
    separador("3) Precio delayed: reqMarketDataType(3) — T34")
    # La cuenta paper no tiene suscripcion de datos en tiempo real, asi
    # que el tipo 3 (delayed, ~15 min) es lo unico disponible. La pregunta
    # que resuelve este bloque: ib_async mapea los ticks delayed (tipos
    # 66-76) a los campos bid/ask/last de siempre, o los deja aparte?
    ib.reqMarketDataType(3)

    contrato = Stock("AMZN", "SMART", "USD")
    ib.qualifyContracts(contrato)
    print(f"Contrato cualificado: conId={contrato.conId}, "
          f"exchange={contrato.exchange}, primary={contrato.primaryExchange}\n")

    print("--- 3a) snapshot=True (una foto y se cierra sola)")
    ticker = ib.reqMktData(contrato, "", snapshot=True)
    ib.sleep(4)
    for k, v in sorted(campos(ticker, saltar=("contract", "ticks", "domTicks",
                                              "bidGreeks", "askGreeks",
                                              "lastGreeks", "modelGreeks")).items()):
        if v == v and v not in ("", 0, [], None, False):  # v==v descarta nan
            print(f"  {k} = {v!r}")
    print(f"\n  marketDataType del ticker = {ticker.marketDataType!r}"
          "   (1 live, 2 frozen, 3 delayed, 4 delayed-frozen)")

    print("\n--- 3b) streaming (snapshot=False) y cancelacion manual")
    ticker2 = ib.reqMktData(contrato, "", snapshot=False)
    ib.sleep(6)
    print(f"  last={ticker2.last!r}  close={ticker2.close!r}  "
          f"bid={ticker2.bid!r}  ask={ticker2.ask!r}")
    print(f"  time={ticker2.time!r}  marketDataType={ticker2.marketDataType!r}")
    ib.cancelMktData(contrato)

    print("\n--- 3c) tipo 4 (delayed-frozen): ultimo cierre con mercado cerrado")
    # Con el mercado cerrado el tipo 3 puede no devolver nada. El 4 da el
    # ultimo valor congelado, que es lo que salva la demo de la defensa si
    # se defiende por la manana.
    ib.reqMarketDataType(4)
    ticker3 = ib.reqMktData(contrato, "", snapshot=False)
    ib.sleep(6)
    print(f"  last={ticker3.last!r}  close={ticker3.close!r}  "
          f"marketDataType={ticker3.marketDataType!r}")
    ib.cancelMktData(contrato)

    ib.disconnect()
    print("\nSondeo terminado.")


if __name__ == "__main__":
    main()