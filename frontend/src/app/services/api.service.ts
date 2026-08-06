/**
 * Unico punto del frontend que conoce la existencia de HTTP.
 *
 * Los componentes piden datos y reciben objetos tipados; no construyen
 * URLs ni saben que hay un backend detras. Es la contrapartida en el
 * cliente de lo que app/broker hace en el servidor con ib_async: si el
 * dia de manana la API cambia de forma, se toca este fichero y ninguno mas.
 */

import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  AccountSummary,
  Instrument,
  OrderRequest,
  OrderResult,
  OrderValidation,
  Portfolio,
  Quote,
  SessionInfo,
  StatusInfo,
} from '../models/api.models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiUrl;

  /** Estado del servicio. Responde aunque IB Gateway este caido. */
  getStatus(): Observable<StatusInfo> {
    return this.http.get<StatusInfo>(`${this.base}/status`);
  }

  /** Estado de la conexion con IB. Tampoco falla si no hay conexion. */
  getSession(): Observable<SessionInfo> {
    return this.http.get<SessionInfo>(`${this.base}/session`);
  }

  /** Resumen de cuenta. Devuelve 503 si IB Gateway no esta disponible. */
  getAccount(): Observable<AccountSummary> {
    return this.http.get<AccountSummary>(`${this.base}/account`);
  }

  /** Cartera valorada. Devuelve 503 si IB Gateway no esta disponible. */
  getPortfolio(): Observable<Portfolio> {
    return this.http.get<Portfolio>(`${this.base}/portfolio`);
  }

  // -------------------------------------------------------------------
  // Operativa (T58, T59)
  // -------------------------------------------------------------------

  /**
   * Busca instrumentos por ticker o nombre.
   *
   * El backend limita 'q' a 40 caracteres y devuelve como mucho 'limit'
   * resultados. La lista puede venir vacia sin ser un error: significa que
   * IB no reconocio el texto, y el componente lo trata como "sin
   * resultados", no como un fallo.
   */
  searchInstruments(q: string, limit = 20): Observable<Instrument[]> {
    const params = new HttpParams().set('q', q).set('limit', limit);
    return this.http.get<Instrument[]>(`${this.base}/instruments`, { params });
  }

  /**
   * Ultimo precio conocido de un instrumento, por su con_id.
   *
   * Devuelve 404 si el con_id no existe. El precio puede llegar con campos
   * a null (mercado cerrado): eso lo interpreta quien lo pinta, no este
   * servicio.
   */
  getQuote(conId: number): Observable<Quote> {
    return this.http.get<Quote>(`${this.base}/instruments/${conId}/quote`);
  }

  /**
   * Comprueba una orden SIN enviarla.
   *
   * Devuelve siempre 200 con un veredicto: accepted=false no es un error
   * HTTP, es un "no" con sus motivos. El componente pinta reasons y
   * warnings, y solo habilita el envio si accepted es true.
   */
  validateOrder(order: OrderRequest): Observable<OrderValidation> {
    return this.http.post<OrderValidation>(`${this.base}/orders/validate`, order);
  }

  /**
   * Envia una orden al mercado.
   *
   * El backend la vuelve a validar antes de cursarla: este metodo no es un
   * atajo que se salte la comprobacion. El desenlace viaja en el campo
   * 'estado' del OrderResult, no en el codigo HTTP.
   */
  submitOrder(order: OrderRequest): Observable<OrderResult> {
    return this.http.post<OrderResult>(`${this.base}/orders`, order);
  }

  /**
   * Consulta el estado de una orden ya enviada, por su order_id.
   *
   * El componente lo sondea tras enviar una orden que quedo viva, hasta
   * que resuelve. Devuelve 404 si el id no existe en esta sesion.
   */
  getOrder(orderId: number): Observable<OrderResult> {
    return this.http.get<OrderResult>(`${this.base}/orders/${orderId}`);
  }
}
