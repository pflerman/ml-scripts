#!/usr/bin/env python3
"""
Script para pausar/activar productos
Cuenta: PALISHOPPING
Autor: Pablo Flerman
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from rich import box

from ml_api import (
    MercadoLibreAPI, console, show_header,
    sincronizar_productos, verificar_cache_al_inicio,
    CREDENTIALS_FILE, DB_FILE
)
from ml_db import ProductDatabase


class ProductPauser:
    """Clase principal para pausar/activar productos"""

    def __init__(self):
        self.api = MercadoLibreAPI(CREDENTIALS_FILE)
        self.db = ProductDatabase(DB_FILE)
        self.user_id = self.api.credentials['user_id']

    def show_menu(self) -> str:
        """Muestra el menú principal y retorna la opción seleccionada"""
        console.print("[bold]Opciones:[/bold]")
        console.print("  [cyan]1[/cyan] - Listar productos activos")
        console.print("  [cyan]2[/cyan] - Listar productos pausados")
        console.print("  [cyan]3[/cyan] - Pausar producto por ID")
        console.print("  [cyan]4[/cyan] - Activar producto por ID")
        console.print("  [cyan]5[/cyan] - Buscar y pausar/activar")
        console.print("  [cyan]6[/cyan] - 🔄 Sincronizar con MercadoLibre")
        console.print("  [cyan]7[/cyan] - Salir")
        console.print()

        return Prompt.ask("Seleccioná una opción", choices=["1", "2", "3", "4", "5", "6", "7"])

    def list_by_status(self, status: str = 'active'):
        """Lista productos filtrados por status"""
        status_text = "Activos" if status == 'active' else "Pausados"
        console.print(f"\n[bold cyan]💾 Cargando productos {status_text.lower()} desde cache...[/bold cyan]")

        try:
            all_items = self.db.get_all_cached_products(status=status, order_by='title')

            if not all_items:
                console.print(f"[yellow]⚠️  No hay productos {status_text.lower()} en cache[/yellow]")
                console.print("[yellow]💡 Ejecutá la opción '6 - Sincronizar' para cargar productos[/yellow]")
                return

            items_per_page = 50
            total_pages = (len(all_items) + items_per_page - 1) // items_per_page
            current_page = 0

            while True:
                table = Table(title=f"Productos {status_text} - Página {current_page + 1}/{total_pages} ({len(all_items)} total)",
                             box=box.ROUNDED, show_lines=True)
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Título", style="white", max_width=50)
                table.add_column("Precio", style="green", justify="right")
                table.add_column("Stock", style="yellow", justify="center")

                start_idx = current_page * items_per_page
                end_idx = min(start_idx + items_per_page, len(all_items))
                page_items = all_items[start_idx:end_idx]

                for item in page_items:
                    table.add_row(
                        item['id'],
                        item['title'][:50],
                        f"${item['price']:,.2f}",
                        str(item['available_quantity'])
                    )

                console.print(table)
                console.print()

                if total_pages > 1:
                    console.print(f"[dim]Página {current_page + 1} de {total_pages}[/dim]")

                action_text = "pausar" if status == 'active' else "activar"
                options = f"Ingresá el ID del producto para {action_text}"
                if current_page < total_pages - 1:
                    options += ", 'n' para siguiente"
                if current_page > 0:
                    options += ", 'p' para anterior"
                options += ", o 'q' para volver"

                item_id = Prompt.ask(options, default="q")

                if item_id.lower() == 'q':
                    break
                elif item_id.lower() == 'n' and current_page < total_pages - 1:
                    current_page += 1
                    continue
                elif item_id.lower() == 'p' and current_page > 0:
                    current_page -= 1
                    continue
                elif item_id.startswith('MLA'):
                    all_ids = [item['id'] for item in all_items]
                    if item_id in all_ids:
                        if status == 'active':
                            self.pause_by_id(item_id)
                        else:
                            self.activate_by_id(item_id)
                        break
                    else:
                        console.print("[red]❌ ID no válido[/red]")
                else:
                    console.print("[yellow]⚠️  Opción no válida[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error al listar productos: {e}[/red]")

    def pause_by_id(self, item_id: str = None):
        """Pausa un producto por su ID"""
        if not item_id:
            item_id = Prompt.ask("\nIngresá el ID del producto a pausar (ej: MLA1234567)")

        try:
            item = self.db.get_product_by_id(item_id)

            if not item:
                console.print("[yellow]⚠️  Producto no encontrado en cache[/yellow]")
                console.print("[yellow]💡 Sincronizá primero o verificá el ID[/yellow]")
                return

            if item['status'] != 'active':
                console.print(f"[yellow]⚠️  El producto ya está en estado: {item['status']}[/yellow]")
                return

            console.print(Panel(
                f"[bold]ID:[/bold] {item['id']}\n"
                f"[bold]Título:[/bold] {item['title']}\n"
                f"[bold]Precio:[/bold] ${item['price']:,.2f}\n"
                f"[bold]Stock:[/bold] {item['available_quantity']} unidades\n"
                f"[bold]Estado actual:[/bold] [green]Activo[/green]",
                title="📦 Producto a Pausar",
                border_style="yellow",
                box=box.ROUNDED
            ))

            if Confirm.ask("\n¿Pausar este producto?", default=False):
                console.print("\n[cyan]⏳ Pausando producto en MercadoLibre...[/cyan]")

                if self.api.pause_item(item_id):
                    self.db.update_product_status(item_id, 'paused')
                    console.print(Panel(
                        f"[bold green]✓ Producto pausado exitosamente[/bold green]\n"
                        f"[dim]ID: {item_id}[/dim]\n"
                        f"[dim]El producto ya no aparece en búsquedas públicas[/dim]",
                        border_style="green",
                        box=box.ROUNDED
                    ))
                else:
                    console.print("[red]❌ Error al pausar producto en MercadoLibre[/red]")
            else:
                console.print("[yellow]⚠️  Operación cancelada[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")

    def activate_by_id(self, item_id: str = None):
        """Activa un producto pausado por su ID"""
        if not item_id:
            item_id = Prompt.ask("\nIngresá el ID del producto a activar (ej: MLA1234567)")

        try:
            item = self.db.get_product_by_id(item_id)

            if not item:
                console.print("[yellow]⚠️  Producto no encontrado en cache[/yellow]")
                console.print("[yellow]💡 Sincronizá primero o verificá el ID[/yellow]")
                return

            if item['status'] != 'paused':
                console.print(f"[yellow]⚠️  El producto está en estado: {item['status']}[/yellow]")
                if item['status'] == 'active':
                    console.print("[yellow]El producto ya está activo[/yellow]")
                return

            console.print(Panel(
                f"[bold]ID:[/bold] {item['id']}\n"
                f"[bold]Título:[/bold] {item['title']}\n"
                f"[bold]Precio:[/bold] ${item['price']:,.2f}\n"
                f"[bold]Stock:[/bold] {item['available_quantity']} unidades\n"
                f"[bold]Estado actual:[/bold] [yellow]Pausado[/yellow]",
                title="📦 Producto a Activar",
                border_style="green",
                box=box.ROUNDED
            ))

            if Confirm.ask("\n¿Activar este producto?", default=False):
                console.print("\n[cyan]⏳ Activando producto en MercadoLibre...[/cyan]")

                if self.api.activate_item(item_id):
                    self.db.update_product_status(item_id, 'active')
                    console.print(Panel(
                        f"[bold green]✓ Producto activado exitosamente[/bold green]\n"
                        f"[dim]ID: {item_id}[/dim]\n"
                        f"[dim]El producto ya aparece en búsquedas públicas[/dim]",
                        border_style="green",
                        box=box.ROUNDED
                    ))
                else:
                    console.print("[red]❌ Error al activar producto en MercadoLibre[/red]")
            else:
                console.print("[yellow]⚠️  Operación cancelada[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")

    def search_and_toggle(self):
        """Busca productos por palabra clave y permite pausar/activar"""
        keyword = Prompt.ask("\nIngresá palabra(s) clave para buscar")

        if not keyword.strip():
            console.print("[yellow]⚠️  Debés ingresar al menos una palabra[/yellow]")
            return

        console.print(f"\n[bold cyan]💾 Buscando '{keyword}' en cache...[/bold cyan]")

        try:
            keywords = keyword.lower().split()
            active_items = self.db.search_products_by_title(keywords, status='active')
            paused_items = self.db.search_products_by_title(keywords, status='paused')
            all_items = active_items + paused_items

            if not all_items:
                console.print(f"[yellow]⚠️  No se encontraron productos con '{keyword}'[/yellow]")
                return

            table = Table(title=f"Resultados: '{keyword}' ({len(all_items)} encontrados)",
                         box=box.ROUNDED, show_lines=True)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Título", style="white", max_width=45)
            table.add_column("Precio", style="green", justify="right")
            table.add_column("Estado", style="yellow", justify="center")

            display_items = all_items[:30]
            for item in display_items:
                status_display = "[green]Activo[/green]" if item['status'] == 'active' else "[yellow]Pausado[/yellow]"
                table.add_row(
                    item['id'],
                    item['title'][:45],
                    f"${item['price']:,.2f}",
                    status_display
                )

            console.print(table)

            if len(all_items) > 30:
                console.print(f"[yellow]⚠️  Mostrando los primeros 30 de {len(all_items)} resultados[/yellow]")

            item_id = Prompt.ask("\nIngresá el ID del producto para pausar/activar (o 'q' para volver)", default="q")

            if item_id.lower() == 'q':
                return

            selected = next((item for item in all_items if item['id'] == item_id), None)

            if not selected:
                console.print("[red]❌ ID no válido[/red]")
                return

            if selected['status'] == 'active':
                self.pause_by_id(item_id)
            elif selected['status'] == 'paused':
                self.activate_by_id(item_id)
            else:
                console.print(f"[yellow]⚠️  Producto en estado: {selected['status']}[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error al buscar: {e}[/red]")

    def run(self):
        """Ejecuta el loop principal del programa"""
        verificar_cache_al_inicio(self.db, self.api, self.user_id)

        while True:
            show_header("PAUSAR/ACTIVAR PRODUCTOS - MERCADOLIBRE", self.db)
            choice = self.show_menu()

            if choice == "1":
                self.list_by_status('active')
            elif choice == "2":
                self.list_by_status('paused')
            elif choice == "3":
                self.pause_by_id()
            elif choice == "4":
                self.activate_by_id()
            elif choice == "5":
                self.search_and_toggle()
            elif choice == "6":
                sincronizar_productos(self.api, self.db, self.user_id)
            elif choice == "7":
                console.print("\n[bold cyan]¡Hasta luego![/bold cyan]")
                sys.exit(0)

            console.print("\n")
            Prompt.ask("Presioná Enter para continuar")


def main():
    """Función principal"""
    try:
        pauser = ProductPauser()
        pauser.run()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Programa interrumpido[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error inesperado: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
