"""
test_ib.py — Verificación directa de la conexión Python <-> IB Gateway (T27, T28).
Ejecutar desde backend/ con el venv activado:  python test_ib.py
"""
import os
from dotenv import load_dotenv
from ib_async import IB  

load_dotenv()

HOST = os.getenv("IB_HOST", "127.0.0.1")
PORT = int(os.getenv("IB_PORT", "4002"))
CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))


def main():
    ib = IB()
    print(f"[1/4] Conectando a IB Gateway en {HOST}:{PORT} (clientId={CLIENT_ID})...")
    try:
        ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=10)
    except Exception as e:
        print(f"  ✗ ERROR de conexión: {e}")
        print("  Revisa: ¿IB Gateway arrancado? ¿API socket habilitado? ¿Puerto 4002? ¿Trusted IP 127.0.0.1?")
        return

    print(f"  ✓ Conectado: {ib.isConnected()}")

    print("[2/4] Cuentas gestionadas...")
    accounts = ib.managedAccounts()
    print(f"  ✓ Cuentas: {accounts}")
    if accounts and accounts[0].startswith("D"):
        print("  ✓ Prefijo 'D' -> cuenta PAPER/DEMO confirmada (correcto para el TFM)")
    else:
        print("  ⚠ OJO: la cuenta NO parece paper. Verifica antes de operar.")

    print("[3/4] Resumen de cuenta (accountSummary)...")
    summary = ib.accountSummary()
    for tag in ("NetLiquidation", "TotalCashValue", "AvailableFunds"):
        for s in [x for x in summary if x.tag == tag]:
            print(f"  ✓ {s.tag}: {s.value} {s.currency}")

    print("[4/4] Posiciones actuales...")
    positions = ib.positions()
    if positions:
        for p in positions:
            print(f"  ✓ {p.contract.symbol}: {p.position} @ {p.avgCost}")
    else:
        print("  ✓ Sin posiciones (normal en cuenta demo recién creada)")

    ib.disconnect()
    print("\n✅ CHECKPOINT 2 superado: el backend Python habla con IB Gateway y recupera datos de cuenta.")


if __name__ == "__main__":
    main()