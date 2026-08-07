"""Pruebas de la reconexión con IB Gateway (T29), sin Gateway.

Protegen el arreglo del fallo medido el 07/08/2026 con
scripts/sondea_reconexion.py: al caerse la sesión, las peticiones
concurrentes del polling reconectaban a la vez sobre la misma instancia de
IB y corrompían el socket. Igual que test_rutas.py protege el cableado
URL->función, estas pruebas protegen que la reconexión siga siendo UNA sola
aunque la pidan cinco peticiones a la vez.

No necesitan Gateway: se sustituye la instancia real de IB del módulo por
un doble que cuenta llamadas. Se ejecutan con asyncio.run() para no
depender de pytest-asyncio.
"""

import asyncio

import pytest

from app.broker import ib_client
from app.config import settings


class FakeIB:
    """Doble de ib_async.IB que cuenta conexiones y desconexiones.

    connectAsync duerme un instante a propósito: así, en la prueba de
    concurrencia, las corrutinas se solapan de verdad y el candado tiene
    algo que serializar. Sin esa pausa, la primera terminaría antes de que
    la segunda empezara y la carrera no se probaría.
    """

    def __init__(self):
        self._connected = False
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.market_data_type = None

    def isConnected(self) -> bool:
        return self._connected

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def connectAsync(self, host, port, clientId, timeout):
        self.connect_calls += 1
        await asyncio.sleep(0.05)
        self._connected = True

    def reqMarketDataType(self, tipo):
        self.market_data_type = tipo


class FakeIBQueFalla(FakeIB):
    """Como FakeIB pero connectAsync levanta TimeoutError, que es justo lo
    que hace el connectAsync real cuando IB responde 326: agota el timeout
    y no distingue el motivo."""

    async def connectAsync(self, host, port, clientId, timeout):
        self.connect_calls += 1
        raise TimeoutError()


def _instalar(monkeypatch, fake):
    """Sustituye la instancia de IB y renueva el candado del módulo.

    El candado se renueva en cada prueba para que no arrastre estado entre
    ellas ni quede ligado a un bucle de asyncio ya cerrado.
    """
    monkeypatch.setattr(ib_client, "_ib", fake)
    monkeypatch.setattr(ib_client, "_lock", asyncio.Lock())


def test_no_reconecta_si_ya_hay_sesion(monkeypatch):
    fake = FakeIB()
    fake._connected = True
    _instalar(monkeypatch, fake)

    asyncio.run(ib_client.connect())

    assert fake.connect_calls == 0
    assert fake.disconnect_calls == 0


def test_conecta_cuando_no_hay_sesion(monkeypatch):
    fake = FakeIB()
    _instalar(monkeypatch, fake)

    asyncio.run(ib_client.connect())

    assert fake.connect_calls == 1
    assert fake.isConnected()
    assert fake.market_data_type == settings.IB_MARKET_DATA_TYPE


def test_cierra_socket_previo_antes_de_reconectar(monkeypatch):
    # El disconnect() explícito es lo que libera el clientId tras el
    # reinicio del Gateway. Si algún día se quita, esta prueba lo caza.
    fake = FakeIB()
    _instalar(monkeypatch, fake)

    asyncio.run(ib_client.connect())

    assert fake.disconnect_calls == 1


def test_reconexion_concurrente_solo_conecta_una_vez(monkeypatch):
    # La prueba clave: reproduce la carrera de la sección 6 del sondeo.
    # Cinco peticiones piden conexión a la vez; el candado debe hacer que
    # solo UNA llame a connectAsync. Sin candado, esto corrompía el socket.
    fake = FakeIB()
    _instalar(monkeypatch, fake)

    async def cinco_a_la_vez():
        await asyncio.gather(*(ib_client.connect() for _ in range(5)))

    asyncio.run(cinco_a_la_vez())

    assert fake.connect_calls == 1
    assert fake.disconnect_calls == 1
    assert fake.isConnected()


def test_fallo_de_conexion_se_traduce_a_broker_unavailable(monkeypatch):
    fake = FakeIBQueFalla()
    _instalar(monkeypatch, fake)

    with pytest.raises(ib_client.BrokerUnavailable):
        asyncio.run(ib_client.ensure_connected())

    assert fake.connect_calls == 1
