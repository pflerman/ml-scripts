"""
Cliente API de MercadoLibre + funciones de sincronización y UI
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box

from ml_auth import MLAuth, API_BASE_URL

# ── Rutas del proyecto ────────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).parent.parent
CREDENTIALS_FILE = _BASE_DIR / "config" / "ml_credentials_palishopping.json"
DB_FILE = _BASE_DIR / "data" / "ml_operations.db"

# ── Console compartido ────────────────────────────────────────────────────────
console = Console()


# ── Cliente API ───────────────────────────────────────────────────────────────

class MercadoLibreAPI(MLAuth):
    """Cliente para la API de MercadoLibre. Hereda autenticación de MLAuth."""

    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Realiza una petición a la API con autenticación"""
        headers = kwargs.pop('headers', {})
        headers['Authorization'] = f"Bearer {self.credentials['access_token']}"
        url = f"{API_BASE_URL}{endpoint}"

        try:
            response = requests.request(method, url, headers=headers, **kwargs)

            if response.status_code == 401:
                self._refresh_token()
                headers['Authorization'] = f"Bearer {self.credentials['access_token']}"
                response = requests.request(method, url, headers=headers, **kwargs)

            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise Exception(f"Error en petición a ML: {e}")

    def get_user_items(self, offset: int = 0, limit: int = 50, status: str = 'active') -> Dict:
        """Obtiene los productos del usuario"""
        user_id = self.credentials['user_id']
        endpoint = f"/users/{user_id}/items/search"
        params = {'offset': offset, 'limit': limit}
        if status:
            params['status'] = status

        response = self._make_request('GET', endpoint, params=params)
        return response.json()

    def get_all_user_items(self, status: str = None) -> List[str]:
        """Obtiene TODOS los IDs de productos del usuario"""
        all_items = []
        offset = 0
        limit = 50

        while True:
            data = self.get_user_items(offset=offset, limit=limit, status=status)
            item_ids = data.get('results', [])

            if not item_ids:
                break

            all_items.extend(item_ids)

            if len(item_ids) < limit:
                break

            offset += limit

        return all_items

    def get_item_details(self, item_id: str) -> Dict:
        """Obtiene los detalles de un producto específico"""
        endpoint = f"/items/{item_id}"
        response = self._make_request('GET', endpoint)
        return response.json()

    def delete_item(self, item_id: str) -> bool:
        """Cierra/borra un producto"""
        endpoint = f"/items/{item_id}"
        data = {'status': 'closed', 'deleted': True}

        try:
            response = self._make_request('PUT', endpoint, json=data)
            return response.status_code in [200, 201]
        except Exception as e:
            console.print(f"[red]❌ Error al borrar producto: {e}[/red]")
            return False

    def update_item_price(self, item_id: str, new_price: float) -> bool:
        """Actualiza el precio de un producto"""
        endpoint = f"/items/{item_id}"
        data = {"price": new_price}

        try:
            response = self._make_request('PUT', endpoint, json=data)
            return response.status_code == 200
        except Exception as e:
            console.print(f"[red]Error al actualizar precio: {e}[/red]")
            return False

    def pause_item(self, item_id: str) -> bool:
        """Pausa un producto"""
        endpoint = f"/items/{item_id}"
        data = {"status": "paused"}

        try:
            response = self._make_request('PUT', endpoint, json=data)
            return response.status_code == 200
        except Exception as e:
            console.print(f"[red]Error al pausar producto: {e}[/red]")
            return False

    def activate_item(self, item_id: str) -> bool:
        """Activa un producto pausado"""
        endpoint = f"/items/{item_id}"
        data = {"status": "active"}

        try:
            response = self._make_request('PUT', endpoint, json=data)
            return response.status_code == 200
        except Exception as e:
            console.print(f"[red]Error al activar producto: {e}[/red]")
            return False


# ── UI helpers ────────────────────────────────────────────────────────────────

def show_header(title: str, db, account: str = "PALISHOPPING"):
    """Muestra el encabezado estándar con estadísticas"""
    console.clear()

    last_sync = db.get_last_sync()
    if last_sync:
        sync_str = last_sync.strftime("%d/%m/%Y %H:%M")
        hours_ago = (datetime.now() - last_sync).total_seconds() / 3600
        if hours_ago > 24:
            sync_color = "yellow"
            sync_warning = " ⚠️"
        else:
            sync_color = "green"
            sync_warning = ""
    else:
        sync_str = "Nunca"
        sync_color = "red"
        sync_warning = " ⚠️"

    header_text = f"{title}\nCuenta: {account}\nÚltima sync: [{sync_color}]{sync_str}{sync_warning}[/{sync_color}]"

    header = Panel(
        Text.from_markup(header_text, justify="center"),
        box=box.DOUBLE,
        border_style="cyan"
    )
    console.print(header)

    stats = db.get_cache_stats()
    if stats['total'] > 0:
        active = stats['by_status'].get('active', 0)
        paused = stats['by_status'].get('paused', 0)

        stats_text = f"[bold]Total productos:[/bold] {stats['total']} | "
        stats_text += f"[green]Activos:[/green] {active} | "
        if paused > 0:
            stats_text += f"[yellow]Pausados:[/yellow] {paused} | "
        stats_text += f"[bold]Stock total:[/bold] {stats['total_stock']:,} unidades | "
        stats_text += f"[bold]Valor inventario:[/bold] ${stats['total_value']:,.0f}"

        console.print(stats_text)

    console.print()


# ── Sincronización ────────────────────────────────────────────────────────────

def sincronizar_productos(api, db, user_id):
    """Sincroniza todos los productos con MercadoLibre"""
    console.print("\n[bold cyan]🔄 Iniciando sincronización con MercadoLibre...[/bold cyan]\n")

    start_time = time.time()
    stats = {'actualizados': 0, 'nuevos': 0, 'eliminados': 0, 'errores': 0}

    try:
        console.print("[cyan]→ Obteniendo lista de productos desde MercadoLibre...[/cyan]")
        ml_item_ids = api.get_all_user_items(status=None)

        if not ml_item_ids:
            console.print("[yellow]⚠️  No se encontraron productos en MercadoLibre[/yellow]")
            return

        console.print(f"[green]✓ Encontrados {len(ml_item_ids)} productos[/green]\n")

        cached_ids = db.get_cached_item_ids()

        console.print("[cyan]→ Sincronizando productos...[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Sincronizando...", total=len(ml_item_ids))
            products_to_insert = []

            for item_id in ml_item_ids:
                try:
                    item = api.get_item_details(item_id)

                    if item_id in cached_ids:
                        stats['actualizados'] += 1
                    else:
                        stats['nuevos'] += 1

                    products_to_insert.append(item)

                    if len(products_to_insert) >= 10:
                        db.bulk_upsert_products(products_to_insert)
                        products_to_insert = []

                    progress.update(task, advance=1)

                except Exception:
                    stats['errores'] += 1
                    progress.update(task, advance=1)
                    continue

            if products_to_insert:
                db.bulk_upsert_products(products_to_insert)

        console.print("\n[cyan]→ Detectando productos eliminados externamente...[/cyan]")
        ml_ids_set = set(ml_item_ids)
        productos_eliminados = cached_ids - ml_ids_set

        if productos_eliminados:
            for item_id in productos_eliminados:
                db.update_product_status(item_id, 'closed_external')
                stats['eliminados'] += 1
            console.print(f"[yellow]⚠️  {len(productos_eliminados)} productos fueron eliminados externamente[/yellow]")
        else:
            console.print("[green]✓ No hay productos eliminados externamente[/green]")

        db.update_last_sync()
        elapsed_time = time.time() - start_time

        summary_text = f"""
[bold]Productos actualizados:[/bold] {stats['actualizados']}
[bold]Productos nuevos:[/bold] {stats['nuevos']}
[bold]Productos eliminados:[/bold] {stats['eliminados']}
[bold]Errores:[/bold] {stats['errores']}
[bold]Total en cache:[/bold] {len(ml_item_ids)}
[bold]Tiempo:[/bold] {elapsed_time:.1f} segundos
"""

        console.print("\n")
        console.print(Panel(
            summary_text.strip(),
            title="✅ Sincronización Completa",
            border_style="green",
            box=box.DOUBLE
        ))

    except Exception as e:
        console.print(f"\n[red]❌ Error en sincronización: {e}[/red]")
        console.print("[yellow]💡 El cache anterior se mantiene intacto[/yellow]")


def verificar_cache_al_inicio(db, api, user_id):
    """Verifica cache y sugiere sincronización si es necesario"""
    from rich.prompt import Confirm, Prompt

    stats = db.get_cache_stats()
    last_sync = db.get_last_sync()

    if stats['total'] == 0:
        console.print("[yellow]⚠️  Cache vacío - No hay productos en cache local[/yellow]")
        if Confirm.ask("¿Querés sincronizar ahora con MercadoLibre?", default=True):
            sincronizar_productos(api, db, user_id)
            console.print("\n")
            Prompt.ask("Presioná Enter para continuar")
        return

    if last_sync:
        hours_ago = (datetime.now() - last_sync).total_seconds() / 3600
        if hours_ago > 24:
            sync_str = last_sync.strftime("%d/%m/%Y %H:%M")
            console.print(f"[yellow]⚠️  Cache desactualizado (última sync: {sync_str} - hace {hours_ago:.1f} horas)[/yellow]")
            if Confirm.ask("¿Querés sincronizar ahora?", default=False):
                sincronizar_productos(api, db, user_id)
                console.print("\n")
                Prompt.ask("Presioná Enter para continuar")
