"""
sondea_ejecuciones.py — Que devuelve de verdad reqExecutions, antes de T38.

RF-13 pide el historico de operaciones. La fuente NO puede ser trades():
verificado el 04/08 en sondea_ordenes_envio.py, las ordenes completadas no
sobreviven a una reconexion, solo las vivas. reqExecutions consulta el
historico del servidor de IB y no la memoria del cliente, asi que es la
unica fuente que sirve.

Preguntas que este sondeo tiene que contestar, porque cada una cambia la
forma del endpoint:

  1. Que ventana temporal cubre de verdad. La documentacion dice "el dia
     en curso mas los ultimos siete dias habiles", pero eso hay que verlo.
     Si es cierto, el historico de la aplicacion NO puede ser completo y
     eso es una limitacion que hay que declarar en la memoria, no
     descubrirla el dia de la defensa.
  2. Que formato exacto trae execution.time. En otras partes de la API IB
     manda cadenas tipo '20260807 15:30:00 Europe/Madrid'; si aqui llega
     ya como datetime, el mapper se ahorra el parseo, igual que paso con
     las barras historicas (date llegaba como date, cero parseo).
  3. Si Fill trae la comision POBLADA o llega vacia. En T36 aprendimos que
     ib_async crea CommissionReport vacio y lo rellena despues por evento:
     un CommissionReport sin currency hay que IGNORARLO, no tratarlo como
     comision cero. Si aqui pasa lo mismo, el historico no puede prometer
     comisiones.
  4. Si ExecutionFilter filtra por clientId de serie. Importa: si solo
     devuelve lo enviado por nuestro clientId, las operaciones hechas a
     mano desde TWS no apareceran, y el historico mentiria por omision.
  5. Si una orden parcialmente ejecutada produce VARIAS filas. Una compra
     de 100 titulos que cruza en tres trozos son tres ejecuciones: el
     endpoint tiene que decidir si las agrupa por orden o las lista
     sueltas.
  6. Que trae reqExecutions que no traiga fills(): son dos caminos al
     mismo dato y hay que elegir uno con criterio.

Ejecutar desde ~/TFM/backend con el venv activado y el Gateway arrancado.
NO hace falta el mercado abierto: consulta historico, no cotizaciones.

    python scripts/sondea_ejecuciones.py

clientId 73: el 74 lo usa sondea_ordenes_envio, el 75 sondea_ordenes, el
76 instrumentos, el 77 divisas y el 99 compara_posiciones. El 1 es uvicorn.
"""

import os
from datetime import datetime

from dotenv import load_dotenv
from ib_async import IB, ExecutionFilter

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = 73


def separador(titulo):
    print("\n" + "=" * 70)
    print(titulo)
    print("=" * 70)


def campos(obj, saltar=("contract",)):
    """Atributos de datos de un objeto de ib_async.

    Mismo helper que en las sondas anteriores: preguntamos al objeto real
    que campos trae y con que nombre exacto, en vez de fiarnos de la
    documentacion.
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


def volcar(obj, sangria="    ", saltar=("contract",)):
    for k, v in sorted(campos(obj, saltar=saltar).items()):
        print(f"{sangria}{k} = {v!r}  ({type(v).__name__})")


def al_error(reqId, errorCode, errorString, contract):
    # IB no lanza excepciones al rechazar: manda el motivo por este canal.
    # Se filtra el ruido de conexion que ya conocemos de sondas anteriores.
    if errorCode in (2104, 2106, 2107, 2119, 2158, 10167):
        return
    print(f"  errorEvent  reqId={reqId} code={errorCode} :: {errorString}")


def main():
    ib = IB()
    # ib_async trae RequestTimeout=0, o sea esperar indefinidamente. En un
    # script sincrono eso es colgarse sin mensaje.
    ib.RequestTimeout = 30
    ib.errorEvent += al_error

    print(f"Conectando a {HOST}:{PORT} con clientId={CLIENT_ID}...")
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    print(f"Conectado. serverVersion={ib.client.serverVersion()}")

    # ------------------------------------------------------------------
    separador("1) reqExecutions con filtro VACIO: que devuelve por defecto")
    ejecuciones = ib.reqExecutions(ExecutionFilter())
    print(f"  Numero de ejecuciones devueltas: {len(ejecuciones)}")
    print(f"  Tipo de cada elemento: {type(ejecuciones[0]).__name__ if ejecuciones else 'lista vacia'}")

    if not ejecuciones:
        print("\n  SIN EJECUCIONES. Dos causas posibles, y hay que distinguirlas:")
        print("  (a) la ventana de IB no llega a las ordenes de T36, o")
        print("  (b) el filtro por defecto restringe por clientId.")
        print("  El apartado 4 lo aclara.")

    # ------------------------------------------------------------------
    separador("2) Anatomia de la PRIMERA ejecucion, campo por campo")
    if ejecuciones:
        f = ejecuciones[0]
        print("  -- Fill (el envoltorio) --")
        volcar(f, saltar=())
        print("\n  -- Fill.contract --")
        volcar(f.contract, saltar=())
        print("\n  -- Fill.execution --")
        volcar(f.execution, saltar=())
        print("\n  -- Fill.commissionReport --")
        volcar(f.commissionReport, saltar=())
        print("\n  CLAVE: si commissionReport.currency viene vacio, la")
        print("  comision NO es cero, es que no ha llegado (leccion de T36).")

    # ------------------------------------------------------------------
    separador("3) Formato de execution.time y ventana temporal cubierta")
    if ejecuciones:
        tiempos = [f.execution.time for f in ejecuciones]
        t = tiempos[0]
        print(f"  Tipo de execution.time: {type(t).__name__}")
        print(f"  Valor crudo: {t!r}")
        print(f"  Tiene tzinfo: {getattr(t, 'tzinfo', 'no es datetime')}")
        print(f"\n  Mas antigua: {min(tiempos)}")
        print(f"  Mas reciente: {max(tiempos)}")
        print(f"  Ahora: {datetime.now()}")
        print("  -> La distancia hasta la mas antigua es la ventana REAL.")

    # ------------------------------------------------------------------
    separador("4) El filtro por defecto restringe por clientId?")
    # Si el filtro vacio ya trae ordenes de OTROS clientId, entonces no
    # filtra y el historico vera tambien lo hecho a mano desde TWS.
    if ejecuciones:
        ids = sorted({f.execution.clientId for f in ejecuciones})
        print(f"  clientId presentes en el resultado: {ids}")
        print(f"  Nuestro clientId es {CLIENT_ID}.")
        if ids and ids != [CLIENT_ID]:
            print("  -> NO filtra: se ven ejecuciones de otros clientes. Bien:")
            print("     el historico sera completo.")
        else:
            print("  -> Solo aparece un clientId. Ojo: puede ser que filtre o")
            print("     que todo se enviara desde el mismo cliente.")

    print("\n  Ahora con filtro EXPLICITO clientId=0 (todos):")
    todas = ib.reqExecutions(ExecutionFilter(clientId=0))
    print(f"  Devuelve {len(todas)} ejecuciones (antes {len(ejecuciones)})")
    print("  Si el numero sube, el filtro por defecto SI restringia.")

    # ------------------------------------------------------------------
    separador("5) Ejecuciones parciales: varias filas por una misma orden")
    if ejecuciones:
        por_orden = {}
        for f in ejecuciones:
            por_orden.setdefault(f.execution.orderId, []).append(f)
        print(f"  {len(ejecuciones)} ejecuciones repartidas en {len(por_orden)} ordenes")
        for oid, lista in sorted(por_orden.items()):
            total = sum(f.execution.shares for f in lista)
            print(f"    orderId={oid}: {len(lista)} ejecucion(es), {total} titulos")
        parciales = [o for o, l in por_orden.items() if len(l) > 1]
        if parciales:
            print(f"  -> Ordenes troceadas: {parciales}. El endpoint TIENE que")
            print("     decidir si agrupa por orden o lista ejecuciones sueltas.")
        else:
            print("  -> Ninguna troceada en esta muestra. No prueba que no")
            print("     pueda pasar: con cantidades grandes pasa.")

    # ------------------------------------------------------------------
    separador("6) reqExecutions frente a fills(): dos caminos al mismo dato")
    locales = ib.fills()
    print(f"  ib.fills() devuelve {len(locales)} elementos")
    print(f"  ib.reqExecutions() devuelve {len(ejecuciones)} elementos")
    print("  fills() lee la memoria del CLIENTE (lo visto en esta sesion);")
    print("  reqExecutions consulta el SERVIDOR de IB. Si los numeros")
    print("  coinciden es porque ib_async rellena fills() con la respuesta")
    print("  de reqExecutions al conectar, no porque sean equivalentes.")

    ib.disconnect()
    print("\nSondeo terminado.")


if __name__ == "__main__":
    main()
