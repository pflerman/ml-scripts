#!/usr/bin/env python3
"""
Script para modificar precios de productos
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


class PriceUpdater:
    """Clase principal para modificar precios de productos"""

    def __init__(self):
        self.api = MercadoLibreAPI(CREDENTIALS_FILE)
        self.db = ProductDatabase(DB_FILE)
        self.user_id = self.api.credentials['user_id']

    def show_menu(self) -> str:
        """Muestra el menú principal y retorna la opción seleccionada"""
        console.print("[bold]Opciones:[/bold]")
        console.print("  [cyan]1[/cyan] - Listar productos con precios")
        console.print("  [cyan]2[/cyan] - Buscar y modificar precio")
        console.print("  [cyan]3[/cyan] - Modificar precio por ID directo")
        console.print("  [cyan]4[/cyan] - Modificar precios masivamente")
        console.print("  [cyan]5[/cyan] - 🔄 Sincronizar con MercadoLibre")
        console.print("  [cyan]6[/cyan] - Salir")
        console.print()

        return Prompt.ask("Seleccioná una opción", choices=["1", "2", "3", "4", "5", "6"])

    def list_products_with_prices(self):
        """Lista todos los productos activos con sus precios"""
        console.print("\n[bold cyan]💾 Cargando productos desde cache...[/bold cyan]")

        try:
            all_items = self.db.get_all_cached_products(status='active', order_by='price')

            if not all_items:
                console.print("[yellow]⚠️  No hay productos activos en cache[/yellow]")
                console.print("[yellow]💡 Ejecutá la opción '5 - Sincronizar' para cargar productos[/yellow]")
                return

            items_per_page = 50
            total_pages = (len(all_items) + items_per_page - 1) // items_per_page
            current_page = 0

            while True:
                table = Table(title=f"Productos con Precios - Página {current_page + 1}/{total_pages} ({len(all_items)} total)",
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

                options = "Ingresá el ID del producto para cambiar precio"
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
                        self.update_price_by_id(item_id)
                        break
                    else:
                        console.print("[red]❌ ID no válido[/red]")
                else:
                    console.print("[yellow]⚠️  Opción no válida[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error al listar productos: {e}[/red]")

    def search_and_update(self):
        """Busca productos por palabra clave y permite modificar precio"""
        keyword = Prompt.ask("\nIngresá palabra(s) clave para buscar")

        if not keyword.strip():
            console.print("[yellow]⚠️  Debés ingresar al menos una palabra[/yellow]")
            return

        console.print(f"\n[bold cyan]💾 Buscando '{keyword}' en cache...[/bold cyan]")

        try:
            keywords = keyword.lower().split()
            matched_items = self.db.search_products_by_title(keywords, status='active')

            if not matched_items:
                console.print(f"[yellow]⚠️  No se encontraron productos con '{keyword}'[/yellow]")
                return

            table = Table(title=f"Resultados: '{keyword}' ({len(matched_items)} encontrados)",
                         box=box.ROUNDED, show_lines=True)
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Título", style="white", max_width=50)
            table.add_column("Precio Actual", style="green", justify="right")
            table.add_column("Stock", style="yellow", justify="center")

            display_items = matched_items[:30]
            for item in display_items:
                table.add_row(
                    item['id'],
                    item['title'][:50],
                    f"${item['price']:,.2f}",
                    str(item['available_quantity'])
                )

            console.print(table)

            if len(matched_items) > 30:
                console.print(f"[yellow]⚠️  Mostrando los primeros 30 de {len(matched_items)} resultados[/yellow]")

            item_id = Prompt.ask("\nIngresá el ID del producto para cambiar precio (o 'q' para volver)", default="q")

            matched_ids = [item['id'] for item in matched_items]
            if item_id.lower() != 'q' and item_id in matched_ids:
                self.update_price_by_id(item_id)
            elif item_id.lower() != 'q':
                console.print("[red]❌ ID no válido[/red]")

        except Exception as e:
            console.print(f"[red]❌ Error al buscar: {e}[/red]")

    def update_price_by_id(self, item_id: str = None):
        """Modifica el precio de un producto específico"""
        if not item_id:
            item_id = Prompt.ask("\nIngresá el ID del producto (ej: MLA1234567)")

        try:
            item = self.db.get_product_by_id(item_id)

            if not item:
                console.print("[yellow]⚠️  Producto no encontrado en cache[/yellow]")
                console.print("[yellow]💡 Sincronizá primero o verificá el ID[/yellow]")
                return

            console.print(Panel(
                f"[bold]ID:[/bold] {item['id']}\n"
                f"[bold]Título:[/bold] {item['title']}\n"
                f"[bold]Precio actual:[/bold] [green]${item['price']:,.2f}[/green]\n"
                f"[bold]Stock:[/bold] {item['available_quantity']} unidades",
                title="📦 Producto Seleccionado",
                border_style="blue",
                box=box.ROUNDED
            ))

            new_price_str = Prompt.ask(f"\nIngresá el nuevo precio (actual: ${item['price']:,.2f})")

            try:
                new_price = float(new_price_str.replace(',', '').replace('$', ''))
            except ValueError:
                console.print("[red]❌ Precio inválido[/red]")
                return

            if new_price <= 0:
                console.print("[red]❌ El precio debe ser mayor a 0[/red]")
                return

            change_percent = ((new_price - item['price']) / item['price']) * 100
            change_color = "green" if change_percent > 0 else "red" if change_percent < 0 else "yellow"

            console.print(f"\n[bold]Precio anterior:[/bold] ${item['price']:,.2f}")
            console.print(f"[bold]Precio nuevo:[/bold] ${new_price:,.2f}")
            console.print(f"[bold]Cambio:[/bold] [{change_color}]{change_percent:+.1f}%[/{change_color}]")

            if Confirm.ask("\n¿Confirmar cambio de precio?", default=False):
                console.print("\n[cyan]⏳ Actualizando precio en MercadoLibre...[/cyan]")

                if self.api.update_item_price(item_id, new_price):
                    self.db.update_product_price(item_id, new_price)
                    console.print(Panel(
                        f"[bold green]✓ Precio actualizado exitosamente[/bold green]\n"
                        f"[dim]Producto: {item_id}[/dim]\n"
                        f"[dim]Nuevo precio: ${new_price:,.2f}[/dim]",
                        border_style="green",
                        box=box.ROUNDED
                    ))
                else:
                    console.print("[red]❌ Error al actualizar precio en MercadoLibre[/red]")
            else:
                console.print("[yellow]⚠️  Operación cancelada[/yellow]")

        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")

    def update_prices_bulk(self):
        """Modifica precios de múltiples productos por porcentaje"""
        console.print("\n[bold cyan]📊 Modificación Masiva de Precios[/bold cyan]\n")

        keyword = Prompt.ask("Ingresá palabra clave para filtrar (o Enter para todos los productos)", default="")

        if keyword.strip():
            keywords = keyword.lower().split()
            products = self.db.search_products_by_title(keywords, status='active')
        else:
            products = self.db.get_all_cached_products(status='active')

        if not products:
            console.print("[yellow]⚠️  No hay productos para modificar[/yellow]")
            return

        console.print(f"[bold]Productos encontrados:[/bold] {len(products)}")

        percent_str = Prompt.ask("\nIngresá porcentaje de cambio (ej: +10 para aumentar 10%, -5 para bajar 5%)")

        try:
            percent = float(percent_str.replace('%', '').replace('+', ''))
        except ValueError:
            console.print("[red]❌ Porcentaje inválido[/red]")
            return

        if percent == 0:
            console.print("[yellow]⚠️  Porcentaje no puede ser 0[/yellow]")
            return

        console.print(f"\n[bold]Preview de cambios (primeros 10):[/bold]")
        preview_table = Table(box=box.SIMPLE)
        preview_table.add_column("Producto", style="white", max_width=40)
        preview_table.add_column("Precio Actual", style="cyan", justify="right")
        preview_table.add_column("Precio Nuevo", style="green", justify="right")
        preview_table.add_column("Cambio", justify="right")

        for item in products[:10]:
            old_price = item['price']
            new_price = old_price * (1 + percent / 100)
            change_color = "green" if percent > 0 else "red"

            preview_table.add_row(
                item['title'][:40],
                f"${old_price:,.2f}",
                f"${new_price:,.2f}",
                f"[{change_color}]{percent:+.1f}%[/{change_color}]"
            )

        console.print(preview_table)

        if len(products) > 10:
            console.print(f"[dim]... y {len(products) - 10} productos más[/dim]")

        warning_text = f"""
[bold yellow]⚠️  ATENCIÓN - MODIFICACIÓN MASIVA[/bold yellow]

[bold]Total productos a modificar:[/bold] {len(products)}
[bold]Cambio de precio:[/bold] {percent:+.1f}%

[bold red]Esta operación modificará los precios en MercadoLibre[/bold red]
"""
        console.print(Panel(warning_text.strip(), border_style="yellow", box=box.DOUBLE))

        confirmation = Prompt.ask("\n¿Estás seguro? Escribí 'SI' para confirmar", default="NO")

        if confirmation.upper() != 'SI':
            console.print("[yellow]⚠️  Operación cancelada[/yellow]")
            return

        console.print("\n[cyan]⏳ Actualizando precios...[/cyan]\n")
        success_count = 0
        error_count = 0

        for idx, item in enumerate(products, 1):
            item_id = item['id']
            old_price = item['price']
            new_price = round(old_price * (1 + percent / 100), 2)

            console.print(f"[{idx}/{len(products)}] {item_id[:20]}... ", end="")

            if self.api.update_item_price(item_id, new_price):
                self.db.update_product_price(item_id, new_price)
                console.print(f"[green]✓[/green] ${old_price:,.0f} → ${new_price:,.0f}")
                success_count += 1
            else:
                console.print(f"[red]✗ Error[/red]")
                error_count += 1

        console.print(Panel(
            f"[bold green]Exitosos:[/bold green] {success_count}\n"
            f"[bold red]Errores:[/bold red] {error_count}\n"
            f"[bold]Total procesados:[/bold] {len(products)}",
            title="✅ Actualización Masiva Completa",
            border_style="green",
            box=box.DOUBLE
        ))

    def run(self):
        """Ejecuta el loop principal del programa"""
        verificar_cache_al_inicio(self.db, self.api, self.user_id)

        while True:
            show_header("MODIFICAR PRECIOS - MERCADOLIBRE", self.db)
            choice = self.show_menu()

            if choice == "1":
                self.list_products_with_prices()
            elif choice == "2":
                self.search_and_update()
            elif choice == "3":
                self.update_price_by_id()
            elif choice == "4":
                self.update_prices_bulk()
            elif choice == "5":
                sincronizar_productos(self.api, self.db, self.user_id)
            elif choice == "6":
                console.print("\n[bold cyan]¡Hasta luego![/bold cyan]")
                sys.exit(0)

            console.print("\n")
            Prompt.ask("Presioná Enter para continuar")


def main():
    """Función principal"""
    try:
        updater = PriceUpdater()
        updater.run()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Programa interrumpido[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error inesperado: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
