/**
 * Contrato de datos con el backend.
 *
 * Estas interfaces son el espejo exacto de los modelos Pydantic de
 * backend/app/models/. Los nombres de campo se mantienen en snake_case a
 * proposito: son los que viaja el JSON. Renombrarlos a camelCase obligaria
 * a un mapeo en el cliente que solo existiria por estetica y que seria un
 * segundo sitio donde equivocarse.
 *
 * Se escriben a mano y no se generan desde el openapi.json. La alternativa
 * (openapi-typescript) daria garantia automatica de que cliente y servidor
 * no divergen, pero anade una dependencia y un paso de build. Con este
 * tamano no compensa; si la API creciera, si.
 */

/** Estado del propio servicio. No consulta a Interactive Brokers. */
export interface StatusInfo {
  service: string;
  status: string;
  api_version: string;
}

/** Estado de la sesion con IB Gateway. */
export interface SessionInfo {
  connected: boolean;
  host: string;
  port: number;
  client_id: number;
  accounts: string[];
}

/** Resumen economico de la cuenta, en su divisa base. */
export interface AccountSummary {
  account_id: string;
  currency: string;
  net_liquidation: number;
  total_cash: number;
  available_funds: number;
  buying_power: number;
}

/**
 * Una posicion abierta, ya valorada por IB.
 *
 * Los campos sin sufijo estan en la divisa en que cotiza el instrumento
 * (currency). Los que acaban en _base estan convertidos a la divisa base
 * de la cuenta y son los unicos que pueden sumarse entre posiciones.
 */
export interface Position {
  symbol: string;
  sec_type: string;
  currency: string;
  exchange: string;
  quantity: number;

  avg_cost: number;
  market_price: number;
  market_value: number;
  unrealized_pnl: number;
  realized_pnl: number;

  fx_rate: number;
  market_value_base: number;
  cost_base: number;
  unrealized_pnl_base: number;
}

/** Cartera completa. Todos los totales estan en base_currency. */
export interface Portfolio {
  account_id: string;
  base_currency: string;
  positions: Position[];
  total_market_value: number;
  total_cost: number;
  total_unrealized_pnl: number;
}

// ---------------------------------------------------------------------
// Operativa: instrumentos, precio, validacion y envio de ordenes (T58, T59)
//
// Espejo de los Pydantic de backend/app/models/instrument.py, quote.py y
// order.py, verificados contra DUN684545 el 04/08/2026. Mismo criterio que
// arriba: snake_case, los nombres que viajan en el JSON, sin remapear.
// ---------------------------------------------------------------------

/**
 * Un instrumento localizado en la busqueda.
 *
 * El identificador que importa es con_id, no symbol: "AMZN" son cinco
 * cotizaciones distintas de la misma empresa en cinco divisas, y el ticker
 * no elige entre ellas. Todo lo que venga despues (precio, orden) va con
 * con_id.
 */
export interface Instrument {
  con_id: number;
  symbol: string;
  name: string;
  sec_type: string;
  currency: string;
  exchange: string;
}

/**
 * Ultimo precio conocido de un instrumento.
 *
 * Todos los precios son opcionales (number | null) a proposito: fuera de
 * horario o en un valor sin negociacion, IB no manda precio, y un cero
 * seria mentira. null significa "no hay dato"; 0 es un precio.
 *
 * quote_time es el momento al que corresponde el precio; received_at, el
 * momento en que lo recibimos. Con datos retrasados difieren ~15 min, y
 * confundirlos haria creer que el precio es de ahora mismo.
 */
export interface Quote {
  con_id: number;
  symbol: string;
  currency: string;
  exchange: string;

  last: number | null;
  bid: number | null;
  ask: number | null;
  close: number | null;
  volume: number | null;

  change: number | null;
  change_pct: number | null;

  delayed: boolean;
  market_data_type: number;

  quote_time: string | null;
  received_at: string;
}

/**
 * La orden que el usuario quiere comprobar o enviar.
 *
 * Es lo unico que viaja del cliente al backend: los cinco campos del
 * cuerpo de POST /orders/validate y POST /orders. Solo MKT y LMT. En una
 * limitada, limit_price es obligatorio; en una de mercado, debe ir nulo.
 */
export interface OrderRequest {
  con_id: number;
  action: 'BUY' | 'SELL';
  order_type: 'MKT' | 'LMT';
  quantity: number;
  limit_price: number | null;
}

/**
 * Lo que contesta IB a la comprobacion previa, ya traducido.
 *
 * accepted_by_broker es un booleano propio, no el status crudo de IB: IB
 * devuelve 'PreSubmitted' tambien cuando rechaza, asi que fiarse del
 * status daria por buena una orden tumbada. Los margenes son informativos:
 * son la magnitud del apalancamiento que la aplicacion NO ofrece, y
 * explican por que IB aceptaria ordenes que nosotros rechazamos.
 */
export interface BrokerPreview {
  accepted_by_broker: boolean;
  broker_status: string;
  broker_message: string;
  error_code: number | null;
  warning_text: string;

  commission: number | null;
  commission_currency: string;

  init_margin_change: number | null;
  maint_margin_change: number | null;
  equity_with_loan_change: number | null;

  con_id: number;
  symbol: string;
  currency: string;
  exchange: string;
}

/**
 * El veredicto completo sobre una orden, antes de enviarla.
 *
 * Es la respuesta de POST /orders/validate y el nucleo del panel previo:
 * accepted decide si el boton de enviar existe, y reasons/warnings son el
 * texto que se ensena al usuario. El resto son las cifras del desglose
 * (coste, comision, efectivo antes y despues) para que el usuario pueda
 * comprobar la cuenta por su cuenta.
 *
 * cash_available y cash_after estan en divisa base. La validacion es
 * contra EFECTIVO, no contra poder de compra: no hay operativa apalancada.
 */
export interface OrderValidation {
  accepted: boolean;
  reasons: string[];
  warnings: string[];

  con_id: number;
  symbol: string;
  action: string;
  order_type: string;
  quantity: number;
  limit_price: number | null;

  reference_price: number | null;
  price_source: string;
  buffer_pct: number;

  currency: string;
  base_currency: string;
  fx_rate: number;
  estimated_cost: number;
  estimated_cost_base: number;
  commission: number | null;
  commission_currency: string;
  commission_base: number;
  total_base: number;

  cash_available: number;
  cash_after: number;
  position_quantity: number;

  broker: BrokerPreview | null;
}

/**
 * El resultado de enviar una orden al mercado.
 *
 * Respuesta de POST /orders y de GET /orders/{order_id}. El frontend
 * decide que pintar mirando 'estado', no el codigo HTTP: la peticion
 * siempre es correcta, lo que varia es el desenlace. 'estado' es un
 * vocabulario propio (ejecutada, activa, rechazada, cancelada, no_enviada)
 * y no el status crudo de IB.
 *
 * order_id es el identificador para el seguimiento con GET. commission es
 * la REAL de la ejecucion, no la estimada del preview: en una limitada
 * viva todavia no hay ejecucion y es null. validation es el veredicto
 * previo por el que paso la orden, y trae el desglose para el resumen.
 */
export interface OrderResult {
  estado: 'ejecutada' | 'activa' | 'rechazada' | 'cancelada' | 'no_enviada';

  order_id: number;
  perm_id: number;

  con_id: number;
  symbol: string;
  action: string;
  order_type: string;
  quantity: number;
  limit_price: number | null;

  filled_quantity: number;
  remaining_quantity: number;
  avg_fill_price: number | null;

  commission: number | null;
  commission_currency: string;

  broker_status: string;
  broker_message: string;
  error_code: number | null;

  validation: OrderValidation | null;

  submitted_at: string | null;
}
