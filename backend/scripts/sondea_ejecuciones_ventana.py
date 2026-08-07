"""
sondea_ejecuciones_ventana.py — Por que reqExecutions devolvio CERO (T38).

El sondeo del 07/08 devolvio lista vacia con filtro por defecto. Este
script distingue las tres causas posibles, porque cada una lleva a un
diseno distinto de RF-13:

  (a) La ventana de IB no llega al 04/08. Entonces el historico NO puede
      salir de reqExecutions solo: habria que PERSISTIR las ejecuciones
      segun ocurren. Cambia el alcance.
  (b) El filtro necesita un 'time' explicito. Entonces se arregla pasando
      la fecha y no hay cambio de alcance.
  (c) No hubo ejecuciones que recuperar. Se descarta mirando la cartera.

Nota sobre el sondeo anterior: ExecutionFilter() ya trae clientId=0, asi
que las dos llamadas de aquel apartado 4 eran la MISMA. No probaba nada.

Ejecutar desde ~/TFM/backend con el venv activado y el Gateway arrancado.
No hace falta mercado abierto.

    python scripts/sondea_ejecuciones_ventana.py

clientId 72, para no chocar con el 73 del sondeo anterior.
"""

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from ib_async import IB, ExecutionFilter

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 72


def separador(titulo):
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def al_error(reqId, errorCode, errorString, contract):
    if errorCode in (2104, 2106, 2107, 2119, 2158, 10167):
        return
    print(f"  errorEvent  reqId={reqId} code={errorCode} :: {errorString}")


def probar_filtro(ib, etiqueta, filtro):
    """Lanza reqExecutions y resume el resultado.

    Se captura la excepcion porque un formato de fecha que IB no entiende
    puede llegar como error o como caducidad, y queremos seguir probando
    los demas formatos en vez de morir en el primero.
    """
    print(f"\n  {etiqueta}")
    try:
        res = ib.reqExecutions(filtro)
    except Exception as e:
        print(f"    EXCEPCION: {type(e).__name__}: {e}")
        return []
    print(f"    -> {len(res)} ejecuciones")
    for f in res[:5]:
        e = f.execution
        print(f"       {e.time}  {e.side} {e.shares} {f.contract.symbol} "
              f"@ {e.price}  orderId={e.orderId} clientId={e.clientId}")
    return res


def main():
    ib = IB()
    ib.RequestTimeout = 30
    ib.errorEvent += al_error

    print(f"Conectando a {HOST}:{PORT} con clientId={CLIENT_ID}...")
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    print(f"Conectado. serverVersion={ib.client.serverVersion()}")
    ib.sleep(2)

    cuentas = ib.managedAccounts()
    cuenta = cuentas[0] if cuentas else ""
    print(f"Cuenta: {cuenta}")
    print(f"Ahora: {datetime.now()}")

    # ------------------------------------------------------------------
    separador("A) Hubo ejecuciones de verdad? (descarta la causa c)")
    # Si hay posiciones abiertas, alguien las compro. Es la prueba de que
    # las ordenes de T36 cruzaron y hay algo que recuperar.
    posiciones = ib.positions(cuenta)
    print(f"  {len(posiciones)} posiciones abiertas")
    for p in posiciones[:10]:
        print(f"    {p.contract.symbol}: {p.position} @ coste {p.avgCost:.2f}")

    # ------------------------------------------------------------------
    separador("B) El filtro necesita 'time'? (distingue a de b)")
    # IB acepta la fecha en dos formatos segun version. Se prueban los dos
    # y ademas varias profundidades, para MEDIR donde esta el corte real
    # de la ventana en vez de fiarnos de la documentacion.
    hoy = datetime.now()
    for dias in (1, 3, 7, 30, 90):
        desde = hoy - timedelta(days=dias)
        probar_filtro(
            ib,
            f"time='{desde:%Y%m%d}-00:00:00' (hace {dias} dias)",
            ExecutionFilter(time=f"{desde:%Y%m%d}-00:00:00"),
        )

    print("\n  Formato antiguo, por si esta version lo prefiere:")
    desde = hoy - timedelta(days=30)
    probar_filtro(
        ib,
        f"time='{desde:%Y%m%d} 00:00:00'",
        ExecutionFilter(time=f"{desde:%Y%m%d} 00:00:00"),
    )

    # ------------------------------------------------------------------
    separador("C) Filtrando por cuenta explicita")
    # Si el filtro vacio no acotaba por cuenta pero este si devuelve algo,
    # el problema era de filtro y no de ventana.
    probar_filtro(ib, f"acctCode='{cuenta}'", ExecutionFilter(acctCode=cuenta))

    # ------------------------------------------------------------------
    separador("D) Fuente alternativa: reqCompletedOrders")
    # Camino distinto al mismo dato. Devuelve ordenes terminadas y no
    # ejecuciones, asi que no trae precio medio ni comision por trozo,
    # pero si la ventana es mayor puede servir de complemento.
    try:
        completadas = ib.reqCompletedOrders(apiOnly=False)
        print(f"  {len(completadas)} ordenes completadas")
        for t in completadas[:10]:
            print(f"    orderId={t.order.orderId} {t.order.action} "
                  f"{t.order.totalQuantity} {t.contract.symbol} "
                  f"estado={t.orderStatus.status}")
    except Exception as e:
        print(f"  EXCEPCION: {type(e).__name__}: {e}")

    ib.disconnect()
    print("\nSondeo terminado.")


if __name__ == "__main__":
    main()
