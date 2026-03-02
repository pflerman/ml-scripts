#!/usr/bin/env python3
"""
Script CLI para borrar productos de MercadoLibre - Versión 2.0
Cuenta: PALISHOPPING
Autor: Pablo Flerman
"""

import sys
import time
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))

from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box

from ml_api import (
    MercadoLibreAPI, console, show_header,
    sincronizar_productos, verificar_cache_al_inicio,
    CREDENTIALS_FILE, DB_FILE
)
from ml_db import ProductDatabase


class ProductDeleter:
    """Clase principal que maneja la interfaz CLI para borrar productos"""

    def __init__(self):
        self.api = MercadoLibreAPI(CREDENTIALS_FILE)
        self.db = ProductDatabase(DB_FILE)
        self.user_id = self.api.credentials['user_id']

    def show_menu(self) -> str:
        """Muestra el menú principal y retorna la opción seleccionada"""
        console.print("[bold]Opciones:[/bold]")
        console.print("  [cyan]1[/cyan] - Listar productos activos (desde cache)")
        console.print("  [cyan]2[/cyan] - Buscar por palabra en título (desde cache)")
        console.print("  [cyan]3[/cyan] - Buscar producto por ID (desde cache)")
        console.print("  [cyan]4[/cyan] - 🔄 Sincronizar con MercadoLibre")
        console.print("  [cyan]5[/cyan] - Ver historial de borrados")
        console.print("  [cyan]6[/cyan] - Salir")
        console.print()

        return Prompt.ask("Seleccioná una opción", choices=["1", "2", "3", "4", "5", "6"])

    def list_active_products(self):
        """Lista todos los productos activos desde el cache local"""
        console.print("\n[bold cyan]💾 Cargando desde cache local...[/bold cyan]")

        try:
            all_items = self.db.get_all_cached_products(status='active', order_by='title')

            if not all_items:
                console.print("[yellow]⚠️  No hay productos activos en cache[/yellow]")
                console.print("[yellow]💡 Ejecutá la opción '4 - Sincronizar' para cargar productos[/yellow]")
                return

            items_per_page = 50
            total_pages = (len(all_items) + items_per_page - 1) // items_per_page
            current_page = 0

            while True:
                table = Table(title=f"Productos Activos - Página {current_page + 1}/{total_pages} ({len(all_items)} total)",
                             box=box.ROUNDED, show_lines=True)
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Título", style="white", max_width=50)
                table.add_column("Precio", style="green", justify="right")
                table.add_column("Stock", style="yellow", justify="center")
                table.add_column("Vendidos", style="magenta", justify="center")

                start_idx = current_page * items_per_page
                end_idx = min(start_idx + items_per_page, len(all_items))
                page_items = all_items[start_idx:end_idx]

                for item in page_items:
                    table.add_row(
                        item['id'],
                        item['title'][:50],
                        f"${item['price']:,.2f}",
                        str(item['available_quantity']),
                        str(item.get('sold_quantity', 0))
                    )

                console.print(table)
                console.print()

                if total_pages > 1:
                    console.print(f"[dim]Página {current_page + 1} de {total_pages}[/dim]")

                options = "Ingresá el ID del producto a borrar"
                if current_page < total_pages - 1:
                    options += ", 'n' para siguiente página"
                if current_page > 0:
                    options += ", 'p' para página anterior"
                options += ", o 'q' para volver"

                item_id = Prompt.ask(options, default="q")

                if item_id.lower() == 'q':
                    break
                elif item_id.lower() == 'n' and current_page < total_pages - 1:
                    current_page += 1
                    console.clear()
                    show_header("BORRAR PRODUCTOS - MERCADOLIBRE", self.db)
                    continue
                elif item_id.lower() == 'p' and current_page > 0:
                    current_page -= 1
                    console.clear()
                    show_header("BORRAR PRODUCTOS - MERCADOLIBRE", self.db)
                    continue
                elif item_id.startswith('MLA'):
                    all_ids = [item['id'] for item in all_items]
                    if item_id in all_ids:
                        self.delete_product(item_id)
                        break
                    else:
                        console.print("[red]❌ ID de producto no válido[/red]")
                        time.sleep(1)
                else:
                    console.print("[yellow]⚠️  Opción no válida[/yellow]")
                    time.sleep(1)

        except Exception as e:
            console.print(f"[red]❌ Error al listar productos: {e}[/red]")

    def search_product_by_id(self):
        """Busca y muestra un producto por su ID (primero en cache, luego en API)"""
        item_id = Prompt.ask("\nIngresá el ID del producto (ej: MLA1234567)")

        try:
            item = self.db.get_product_by_id(item_id)

            if item:
                console.print("[dim]💾 Encontrado en cache local[/dim]")
                if 'ml_data' in item and item['ml_data']:
                    self.show_product_details(item['ml_data'])
                else:
                    self.show_product_details(item)
            else:
                console.print("[yellow]⚠️  No encontrado en cache, buscando en MercadoLibre...[/yellow]")
                item = self.api.get_item_details(item_id)
                self.show_product_details(item)

            if Confirm.ask("\n¿Querés borrar este producto?", default=False):
                self.delete_product(item_id)

        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")

    def search_products_by_keyword(self):
        """Busca productos por palabra(s) clave en el título desde cache"""
        keyword = Prompt.ask("\nIngresá palabra(s) clave para buscar")

        if not keyword.strip():
            console.print("[yellow]⚠️  Debés ingresar al menos una palabra[/yellow]")
            return

        console.print(f"\n[bold cyan]💾 Buscando en cache local '{keyword}'...[/bold cyan]")

        try:
            keywords = keyword.lower().split()
            matched_items = self.db.search_products_by_title(keywords, status='active')

            if not matched_items:
                console.print(f"[yellow]⚠️  No se encontraron productos con '{keyword}'[/yellow]")
                console.print("[yellow]💡 Intentá sincronizar si agregaste productos nuevos[/yellow]")
                return

            total_found = len(matched_items)
            display_items = matched_items[:50]

            table = Table(title=f"Resultados de búsqueda: '{keyword}' - Cache Local",
                         box=box.ROUNDED, show_lines=True)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Título", style="white", max_width=50)
            table.add_column("Precio", style="green", justify="right")
            table.add_column("Stock", style="yellow", justify="center")

            for item in display_items:
                table.add_row(
                    item['id'],
                    item['title'][:50],
                    f"${item['price']:,.2f}",
                    str(item['available_quantity'])
                )

            console.print(table)
            console.print(f"\n[bold]Encontrados:[/bold] {total_found} productos")
            if total_found > 50:
                console.print(f"[yellow]⚠️  Solo se muestran los primeros 50 resultados[/yellow]")

            console.print()
            item_id = Prompt.ask(
                "Ingresá el ID del producto a borrar (o 'q' para volver)",
                default="q"
            )

            matched_ids = [item['id'] for item in matched_items]
            if item_id.lower() != 'q' and item_id in matched_ids:
                self.delete_product(item_id)
            elif item_id.lower() != 'q':
                console.print("[red]❌ ID de producto no válido o no está en los resultados[/red]")

        except Exception as e:
            console.print(f"[red]❌ Error al buscar productos: {e}[/red]")

    def show_product_details(self, item: Dict):
        """Muestra los detalles completos de un producto"""
        details = f"""
[bold]ID:[/bold] {item.get('id', 'N/A')}
[bold]Título:[/bold] {item.get('title', 'N/A')}
[bold]Precio:[/bold] ${item.get('price', 0):,.2f}
[bold]Stock:[/bold] {item.get('available_quantity', 0)} unidades
[bold]Estado:[/bold] {item.get('status', 'N/A')}
[bold]Condición:[/bold] {item.get('condition', 'N/A')}
[bold]Ventas:[/bold] {item.get('sold_quantity', 0)} unidades vendidas
"""
        panel = Panel(details.strip(), title="Detalles del Producto",
                     border_style="blue", box=box.ROUNDED)
        console.print(panel)

    def delete_product(self, item_id: str):
        """Borra un producto con confirmación"""
        try:
            item = self.api.get_item_details(item_id)

            warning_text = f"""
[bold]ID:[/bold] {item_id}
[bold]Título:[/bold] {item.get('title', 'N/A')}
[bold]Precio:[/bold] ${item.get('price', 0):,.2f}
[bold]Stock:[/bold] {item.get('available_quantity', 0)} unidades

[bold red]Esta acción NO se puede deshacer[/bold red]
"""
            console.print(Panel(
                warning_text.strip(),
                title="⚠️  CONFIRMAR BORRADO",
                border_style="red",
                box=box.DOUBLE
            ))

            confirmation = Prompt.ask(
                "\n¿Estás seguro que querés borrar este producto?\nEscribí 'SI' para confirmar",
                default="NO"
            )

            if confirmation.upper() == 'SI':
                if self.api.delete_item(item_id):
                    self.db.save_deleted_product(
                        item_id=item_id,
                        title=item.get('title', ''),
                        price=item.get('price', 0),
                        status=item.get('status', ''),
                        user_id=self.user_id
                    )
                    self.db.update_product_status(item_id, 'closed')

                    console.print(Panel(
                        f"[bold green]✓ Producto {item_id} borrado exitosamente[/bold green]\n[dim]Cache local actualizado[/dim]",
                        border_style="green",
                        box=box.ROUNDED
                    ))
                else:
                    console.print("[red]❌ Error al borrar el producto[/red]")
            else:
                console.print("[yellow]⚠️  Operación cancelada[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")

    def show_deleted_history(self):
        """Muestra el historial de productos borrados"""
        console.print("\n[bold cyan]Historial de Productos Borrados[/bold cyan]\n")

        try:
            history = self.db.get_deleted_history(limit=50)

            if not history:
                console.print("[yellow]⚠️  No hay productos borrados en el historial[/yellow]")
                return

            table = Table(title=f"Últimos {len(history)} productos borrados",
                         box=box.ROUNDED, show_lines=True)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Título", style="white", max_width=50)
            table.add_column("Precio", style="green", justify="right")
            table.add_column("Fecha de Borrado", style="yellow")

            for record in history:
                table.add_row(
                    record['item_id'],
                    record['title'][:50] if record['title'] else 'N/A',
                    f"${record['price']:,.2f}" if record['price'] else 'N/A',
                    record['deleted_at']
                )

            console.print(table)

        except Exception as e:
            console.print(f"[red]❌ Error al obtener historial: {e}[/red]")

    def run(self):
        """Ejecuta el loop principal del programa"""
        verificar_cache_al_inicio(self.db, self.api, self.user_id)

        while True:
            show_header("BORRAR PRODUCTOS - MERCADOLIBRE", self.db)
            choice = self.show_menu()

            if choice == "1":
                self.list_active_products()
            elif choice == "2":
                self.search_products_by_keyword()
            elif choice == "3":
                self.search_product_by_id()
            elif choice == "4":
                sincronizar_productos(self.api, self.db, self.user_id)
            elif choice == "5":
                self.show_deleted_history()
            elif choice == "6":
                console.print("\n[bold cyan]¡Hasta luego![/bold cyan]")
                sys.exit(0)

            console.print("\n")
            Prompt.ask("Presioná Enter para continuar")


def main():
    """Función principal"""
    try:
        deleter = ProductDeleter()
        deleter.run()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Programa interrumpido por el usuario[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error inesperado: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
