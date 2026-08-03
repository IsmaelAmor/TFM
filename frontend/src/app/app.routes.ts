import { Routes } from '@angular/router';

import { Cartera } from './pages/cartera/cartera';

export const routes: Routes = [
  { path: 'cartera', component: Cartera, title: 'Cartera' },
  { path: '', pathMatch: 'full', redirectTo: 'cartera' },
  { path: '**', redirectTo: 'cartera' },
];
