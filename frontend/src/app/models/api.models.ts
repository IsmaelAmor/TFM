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
