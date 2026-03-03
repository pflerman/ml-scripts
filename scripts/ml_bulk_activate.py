#!/usr/bin/env python3
"""
Script para activar productos pausados en lote asignando stock
Cuenta: PALISHOPPING
Autor: Pablo Flerman
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box

from ml_api import (
    MercadoLibreAPI, console, show_header,
    sincronizar_productos, verificar_cache_al_inicio,
    CREDENTIALS_FILE, DB_FILE
)
from ml_db import ProductDatabase


def _tiene_variantes(product: dict) -> bool:
    """Detecta si un producto tiene variantes leyendo ml_data del cache"""
    ml_data = product.get('ml_data') or {}
    if isinstance(ml_data, str):
        try:
            ml_data = json.loads(ml_data)
        except Exception:
            return False
    variaciones = ml_data.get('variations', [])
    return len(variaciones) > 0


class BulkActivator:
    """Activa múltiples productos pausados asignándoles stock"""

    def __init__(self):
        self.api = MercadoLibreAPI(CREDENTIALS_FILE)
        self.db = ProductDatabase(DB_FILE)
        self.user_id = self.api.credentials['user_id']

    def show_menu(self) -> str:
        console.print("[bold]Opciones:[/bold]")
        console.print("  [cyan]1[/cyan] - Buscar pausados por palabra clave")
        console.print("  [cyan]2[/cyan] - Listar todos los pausados")
        console.print("  [cyan]3[/cyan] - 🔄 Sincronizar con MercadoLibre")
        console.print("  [cyan]4[/cyan] - Salir")
        console.print()
        return Prompt.ask("Seleccioná una opción", choices=["1", "2", "3", "4"])

    def buscar_pausados(self):
        """Busca productos pausados por palabra clave"""
        keyword = Prompt.ask("\nIngresá palabra(s) clave para buscar")
        if not keyword.strip():
            console.print("[yellow]⚠️  Debés ingresar al menos una palabra[/yellow]")
            return

        keywords = keyword.lower().split()
        productos = self.db.search_products_by_title(keywords, status='paused')

        if not productos:
            console.print(f"[yellow]⚠️  No se encontraron productos pausados con '{keyword}'[/yellow]")
            return

        self.activar_en_lote(productos, titulo=f"Pausados con '{keyword}'")

    def listar_todos_pausados(self):
        """Lista todos los productos pausados y ofrece activación en lote"""
        productos = self.db.get_all_cached_products(status='paused', order_by='title')

        if not productos:
            console.print("[yellow]⚠️  No hay productos pausados en cache[/yellow]")
            console.print("[yellow]💡 Ejecutá la opción '3 - Sincronizar' para actualizar[/yellow]")
            return

        self.activar_en_lote(productos, titulo="Todos los productos pausados")

    def activar_en_lote(self, productos: list, titulo: str):
        """Flujo completo: tabla → detección variantes → stock → confirmar → progress → resumen"""

        # Separar productos con y sin variantes
        sin_variantes = []
        con_variantes = []

        for p in productos:
            # Enriquecer con ml_data para detectar variantes
            p_full = self.db.get_product_by_id(p['id'])
            if p_full and _tiene_variantes(p_full):
                con_variantes.append(p)
            else:
                sin_variantes.append(p)

        # Mostrar tabla de productos sin variantes (los que se van a activar)
        table = Table(
            title=f"{titulo} — {len(sin_variantes)} producto(s) activables",
            box=box.ROUNDED,
            show_lines=True
        )
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Título", style="white", max_width=50)
        table.add_column("Precio", style="green", justify="right")
        table.add_column("Stock actual", style="yellow", justify="center")

        for p in sin_variantes:
            table.add_row(
                p['id'],
                p['title'][:50],
                f"${p['price']:,.2f}",
                str(p.get('available_quantity', 0))
            )

        console.print(table)

        if not sin_variantes:
            console.print("[yellow]⚠️  Todos los productos encontrados tienen variantes.[/yellow]")
            console.print("[yellow]   Usá ml_activate_variants.py para gestionarlos.[/yellow]")
            return

        # Advertencia sobre productos con variantes que se omiten
        if con_variantes:
            console.print(
                f"\n[yellow]⚠️  Se omiten {len(con_variantes)} producto(s) con variantes "
                f"(usá ml_activate_variants.py para ellos):[/yellow]"
            )
            for p in con_variantes[:5]:
                console.print(f"   [dim]• {p['id']} — {p['title'][:60]}[/dim]")
            if len(con_variantes) > 5:
                console.print(f"   [dim]  ... y {len(con_variantes) - 5} más[/dim]")

        # Input de stock
        console.print()
        stock_str = Prompt.ask(
            f"¿Cuántas unidades de stock asignás a cada producto? "
            f"(se aplicará a los {len(sin_variantes)} productos)"
        )

        try:
            stock = int(stock_str)
        except ValueError:
            console.print("[red]❌ Stock inválido — debe ser un número entero[/red]")
            return

        if stock <= 0:
            console.print("[red]❌ El stock debe ser mayor a 0[/red]")
            return

        # Confirmación
        warning = Panel(
            f"[bold yellow]⚠️  ACTIVACIÓN EN LOTE[/bold yellow]\n\n"
            f"[bold]Productos a activar:[/bold] {len(sin_variantes)}\n"
            f"[bold]Stock por producto:[/bold] {stock} unidades\n\n"
            f"[bold red]Esta operación modificará los productos en MercadoLibre[/bold red]",
            border_style="yellow",
            box=box.DOUBLE
        )
        console.print(warning)

        if not Confirm.ask("\n¿Confirmar activación?", default=False):
            console.print("[yellow]⚠️  Operación cancelada[/yellow]")
            return

        # Progress bar + loop con delay
        console.print()
        exitosos = 0
        errores = 0
        errores_detalle = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Activando productos...", total=len(sin_variantes))

            for p in sin_variantes:
                item_id = p['id']
                progress.update(task, description=f"[cyan]{item_id}")

                try:
                    response = self.api._make_request(
                        'PUT', f"/items/{item_id}",
                        json={"available_quantity": stock}
                    )
                    if response.status_code == 200:
                        self.db.update_product_status(item_id, 'active')
                        exitosos += 1
                    else:
                        errores += 1
                        errores_detalle.append((item_id, f"HTTP {response.status_code}"))
                except Exception as e:
                    errores += 1
                    errores_detalle.append((item_id, str(e)))

                progress.update(task, advance=1)
                time.sleep(1)

        # Resumen
        resumen_color = "green" if errores == 0 else "yellow"
        resumen = (
            f"[bold green]Activados exitosamente:[/bold green] {exitosos}\n"
            f"[bold red]Errores:[/bold red] {errores}\n"
            f"[bold]Stock asignado:[/bold] {stock} unidades c/u\n"
            f"[bold]Total procesados:[/bold] {len(sin_variantes)}"
        )

        if errores_detalle:
            resumen += "\n\n[bold red]Detalle de errores:[/bold red]"
            for eid, emsg in errores_detalle[:5]:
                resumen += f"\n  [dim]• {eid}: {emsg}[/dim]"
            if len(errores_detalle) > 5:
                resumen += f"\n  [dim]  ... y {len(errores_detalle) - 5} más[/dim]"

        console.print(Panel(
            resumen,
            title="✅ Activación en Lote Completa",
            border_style=resumen_color,
            box=box.DOUBLE
        ))

    def run(self):
        """Loop principal"""
        verificar_cache_al_inicio(self.db, self.api, self.user_id)

        while True:
            show_header("ACTIVAR PRODUCTOS EN LOTE - MERCADOLIBRE", self.db)
            choice = self.show_menu()

            if choice == "1":
                self.buscar_pausados()
            elif choice == "2":
                self.listar_todos_pausados()
            elif choice == "3":
                sincronizar_productos(self.api, self.db, self.user_id)
            elif choice == "4":
                console.print("\n[bold cyan]¡Hasta luego![/bold cyan]")
                sys.exit(0)

            console.print("\n")
            Prompt.ask("Presioná Enter para continuar")


def main():
    try:
        activator = BulkActivator()
        activator.run()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Programa interrumpido[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error inesperado: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
