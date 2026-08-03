/**
 * Unico punto del frontend que conoce la existencia de HTTP.
 *
 * Los componentes piden datos y reciben objetos tipados; no construyen
 * URLs ni saben que hay un backend detras. Es la contrapartida en el
 * cliente de lo que app/broker hace en el servidor con ib_async: si el
 * dia de manana la API cambia de forma, se toca este fichero y ninguno mas.
 */

import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  AccountSummary,
  Portfolio,
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
}
