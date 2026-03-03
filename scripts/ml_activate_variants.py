#!/usr/bin/env python3
"""
Script para reactivar variantes de productos en MercadoLibre
Cuenta: PALISHOPPING
Autor: Pablo Flerman
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

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


class VariantActivator:
    """Clase principal para reactivar variantes de productos"""

    def __init__(self):
        self.api = MercadoLibreAPI(CREDENTIALS_FILE)
        self.db = ProductDatabase(DB_FILE)
        self.user_id = self.api.credentials['user_id']

    # ── Menú ──────────────────────────────────────────────────────────────────

    def show_menu(self) -> str:
        console.print("[bold]Opciones:[/bold]")
        console.print("  [cyan]1[/cyan] - Listar productos con variantes pausadas")
        console.print("  [cyan]2[/cyan] - Buscar producto por ID")
        console.print("  [cyan]3[/cyan] - Buscar por palabra en título")
        console.print("  [cyan]4[/cyan] - 🔄 Sincronizar con MercadoLibre")
        console.print("  [cyan]5[/cyan] - Salir")
        console.print()
        return Prompt.ask("Seleccioná una opción", choices=["1", "2", "3", "4", "5"])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _format_attrs(self, variation: Dict) -> str:
        """Formatea los atributos de una variante como string legible"""
        attrs = variation.get('attribute_combinations', [])
        if not attrs:
            return "—"
        return ", ".join(
            f"{a.get('name', '?')}: {a.get('value_name', '?')}"
            for a in attrs
        )

    def _get_paused(self, variations: List[Dict]) -> List[Dict]:
        """Variantes con available_quantity == 0 (sin stock / pausadas)"""
        return [v for v in variations if v.get('available_quantity', 0) == 0]

    def _get_variations_from_cache(self, item_id: str) -> Optional[List[Dict]]:
        """Lee variantes desde ml_data en el cache local (sin llamada a API)"""
        cached = self.db.get_product_by_id(item_id)
        if not cached or not cached.get('ml_data'):
            return None
        return cached['ml_data'].get('variations') or None

    def _get_variations_from_api(self, item_id: str) -> Optional[Dict]:
        """Obtiene el item completo con variantes desde la API"""
        try:
            return self.api.get_item_details(item_id)
        except Exception as e:
            console.print(f"[red]❌ Error al obtener producto de la API: {e}[/red]")
            return None

    # ── Listar productos con variantes pausadas ───────────────────────────────

    def listar_productos_con_variantes(self):
        """
        Lista productos del cache que tienen variantes con stock 0.
        Usa ml_data del cache — sin llamadas a la API.
        """
        console.print("\n[bold cyan]💾 Analizando cache local...[/bold cyan]")

        all_items = self.db.get_all_cached_products()
        if not all_items:
            console.print("[yellow]⚠️  Cache vacío. Usá la opción 4 para sincronizar.[/yellow]")
            return

        found = []
        for item in all_items:
            variations = self._get_variations_from_cache(item['id'])
            if not variations:
                continue
            paused = self._get_paused(variations)
            if paused:
                found.append({
                    'id': item['id'],
                    'title': item['title'],
                    'status': item['status'],
                    'total': len(variations),
                    'paused': len(paused),
                })

        if not found:
            console.print("[yellow]⚠️  No hay productos con variantes sin stock en el cache[/yellow]")
            console.print("[dim]Tip: sincronizá para actualizar el cache[/dim]")
            return

        table = Table(
            title=f"Productos con Variantes Sin Stock ({len(found)} encontrados)",
            box=box.ROUNDED, show_lines=True
        )
        table.add_column("ID Producto", style="cyan", no_wrap=True)
        table.add_column("Título", style="white", max_width=45)
        table.add_column("Estado", justify="center")
        table.add_column("Variantes", style="blue", justify="center")
        table.add_column("Sin stock", style="red", justify="center")

        for item in found:
            st = "[green]Activo[/green]" if item['status'] == 'active' else "[yellow]Pausado[/yellow]"
            table.add_row(item['id'], item['title'][:45], st,
                          str(item['total']), str(item['paused']))

        console.print(table)

        item_id = Prompt.ask(
            "\nIngresá el ID para gestionar sus variantes (o 'q' para volver)",
            default="q"
        )
        if item_id.lower() == 'q':
            return

        valid_ids = {i['id'] for i in found}
        if item_id in valid_ids:
            self.ver_y_gestionar_variantes(item_id)
        else:
            console.print("[red]❌ ID no está en la lista[/red]")

    # ── Buscar por ID ─────────────────────────────────────────────────────────

    def buscar_por_id(self):
        item_id = Prompt.ask("\nIngresá el ID del producto (ej: MLA1234567)")
        item_id = item_id.strip()
        if item_id:
            self.ver_y_gestionar_variantes(item_id)

    # ── Buscar por título ─────────────────────────────────────────────────────

    def buscar_por_titulo(self):
        keyword = Prompt.ask("\nIngresá palabra(s) clave para buscar")
        if not keyword.strip():
            console.print("[yellow]⚠️  Ingresá al menos una palabra[/yellow]")
            return

        keywords = keyword.lower().split()
        activos = self.db.search_products_by_title(keywords, status='active')
        pausados = self.db.search_products_by_title(keywords, status='paused')
        all_results = activos + pausados

        if not all_results:
            console.print(f"[yellow]⚠️  Sin resultados para '{keyword}'[/yellow]")
            return

        table = Table(
            title=f"Resultados: '{keyword}' ({len(all_results)} encontrados)",
            box=box.ROUNDED, show_lines=True
        )
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Título", style="white", max_width=50)
        table.add_column("Estado", justify="center")

        for item in all_results[:25]:
            st = "[green]Activo[/green]" if item['status'] == 'active' else "[yellow]Pausado[/yellow]"
            table.add_row(item['id'], item['title'][:50], st)

        console.print(table)

        item_id = Prompt.ask(
            "\nIngresá el ID para ver variantes (o 'q' para volver)",
            default="q"
        )
        if item_id.lower() == 'q':
            return

        valid_ids = {i['id'] for i in all_results}
        if item_id in valid_ids:
            self.ver_y_gestionar_variantes(item_id)
        else:
            console.print("[red]❌ ID no válido[/red]")

    # ── Ver y gestionar variantes ─────────────────────────────────────────────

    def ver_y_gestionar_variantes(self, item_id: str):
        """
        Muestra la tabla de variantes de un producto.
        Intenta usar el cache; si no hay variantes en cache, llama a la API.
        """
        item_id = item_id.upper().strip()

        # Primero intentar desde cache
        variations = self._get_variations_from_cache(item_id)
        item = None

        if variations is None:
            console.print(f"\n[cyan]⏳ Obteniendo variantes de {item_id} desde la API...[/cyan]")
            item = self._get_variations_from_api(item_id)
            if not item:
                return
            variations = item.get('variations') or []
        else:
            # Para mostrar título y estado necesitamos el item completo
            cached = self.db.get_product_by_id(item_id)
            item = cached.get('ml_data', {}) if cached else {}
            item['id'] = item_id
            if cached:
                item['title'] = cached.get('title', item_id)
                item['status'] = cached.get('status', '?')

        if not variations:
            console.print(f"[yellow]⚠️  El producto {item_id} no tiene variantes[/yellow]")
            return

        title = item.get('title', item_id)
        status_raw = item.get('status', '?')
        status_display = "[green]Activo[/green]" if status_raw == 'active' else "[yellow]Pausado[/yellow]"

        console.print(Panel(
            f"[bold]ID:[/bold] {item_id}\n"
            f"[bold]Título:[/bold] {title}\n"
            f"[bold]Estado:[/bold] {status_display}\n"
            f"[bold]Total variantes:[/bold] {len(variations)}",
            title="📦 Producto Seleccionado",
            border_style="cyan",
            box=box.ROUNDED
        ))

        # Tabla de variantes
        table = Table(
            title=f"Variantes ({len(variations)} total)",
            box=box.ROUNDED, show_lines=True
        )
        table.add_column("#", style="dim", justify="right", width=3)
        table.add_column("ID Variante", style="cyan", no_wrap=True)
        table.add_column("Atributos", style="white", max_width=38)
        table.add_column("Estado", justify="center", width=12)
        table.add_column("Stock", justify="center", width=6)
        table.add_column("Vendidos", style="magenta", justify="center", width=9)

        paused_variations = []
        for idx, var in enumerate(variations, 1):
            qty = var.get('available_quantity', 0)
            sold = var.get('sold_quantity', 0)
            attrs = self._format_attrs(var)

            if qty == 0:
                st = "[red]⏸ Sin stock[/red]"
                paused_variations.append(var)
            else:
                st = "[green]✓ Activo[/green]"

            table.add_row(str(idx), str(var.get('id', '?')), attrs, st, str(qty), str(sold))

        console.print(table)

        if not paused_variations:
            console.print("\n[green]✓ Todas las variantes tienen stock[/green]")
            return

        console.print(f"\n[yellow]{len(paused_variations)} variante(s) sin stock[/yellow]")

        # Sub-menú de acciones
        console.print("\n[bold]Opciones:[/bold]")
        console.print("  [cyan]1[/cyan] - Reactivar variante específica")
        console.print("  [cyan]2[/cyan] - Reactivar TODAS las sin stock")
        console.print("  [cyan]3[/cyan] - Volver")

        choice = Prompt.ask("Seleccioná una opción", choices=["1", "2", "3"])

        if choice == "1":
            # Si hay una sola pausada, preseleccionarla
            if len(paused_variations) == 1:
                default_id = str(paused_variations[0].get('id', ''))
                var_id_input = Prompt.ask(
                    "\nID de la variante a reactivar",
                    default=default_id
                )
            else:
                var_id_input = Prompt.ask("\nIngresá el ID de la variante a reactivar")

            selected = next(
                (v for v in paused_variations if str(v.get('id')) == var_id_input.strip()),
                None
            )
            if not selected:
                console.print("[red]❌ ID de variante no válido o ya tiene stock[/red]")
                return
            self.reactivar_variante(item_id, selected, variations)

        elif choice == "2":
            self.reactivar_todas_pausadas(item_id, title, paused_variations, variations)

    # ── Reactivar una variante ────────────────────────────────────────────────

    def reactivar_variante(
        self,
        item_id: str,
        variation: Dict,
        all_variations: List[Dict]
    ):
        var_id = variation.get('id')
        attrs = self._format_attrs(variation)
        sold = variation.get('sold_quantity', 0)

        console.print(Panel(
            f"[bold]ID Variante:[/bold] {var_id}\n"
            f"[bold]Atributos:[/bold] {attrs}\n"
            f"[bold]Vendidos:[/bold] {sold} unidades\n"
            f"[bold]Stock actual:[/bold] [red]0 (sin stock)[/red]",
            title="⚠️  Reactivar Variante",
            border_style="yellow",
            box=box.ROUNDED
        ))

        stock_str = Prompt.ask("¿Cuántas unidades de stock querés asignar?")
        try:
            new_stock = int(stock_str)
        except ValueError:
            console.print("[red]❌ Valor inválido[/red]")
            return

        if new_stock <= 0:
            console.print("[red]❌ El stock debe ser mayor a 0 para reactivar[/red]")
            return

        if not Confirm.ask(
            f"\n¿Reactivar variante {var_id} ({attrs}) con {new_stock} unidades?",
            default=False
        ):
            console.print("[yellow]⚠️  Operación cancelada[/yellow]")
            return

        console.print("\n[cyan]⏳ Actualizando en MercadoLibre...[/cyan]")

        # Incluir TODAS las variantes en el PUT para no perder las demás
        updated = [
            {"id": v['id'], "available_quantity": new_stock if v['id'] == var_id
             else v.get('available_quantity', 0)}
            for v in all_variations
        ]

        try:
            self.api._make_request('PUT', f"/items/{item_id}", json={"variations": updated})
            console.print(Panel(
                f"[bold green]✓ Variante reactivada exitosamente[/bold green]\n"
                f"[dim]ID: {var_id}[/dim]\n"
                f"[dim]Atributos: {attrs}[/dim]\n"
                f"[dim]Stock asignado: {new_stock} unidades[/dim]",
                border_style="green",
                box=box.ROUNDED
            ))
        except Exception as e:
            console.print(f"[red]❌ Error al reactivar: {e}[/red]")

    # ── Reactivar todas las pausadas ──────────────────────────────────────────

    def reactivar_todas_pausadas(
        self,
        item_id: str,
        title: str,
        paused_variations: List[Dict],
        all_variations: List[Dict]
    ):
        preview_lines = "\n".join(
            f"  • {self._format_attrs(v)} (ID: {v.get('id')})"
            for v in paused_variations[:10]
        )
        if len(paused_variations) > 10:
            preview_lines += f"\n  [dim]... y {len(paused_variations) - 10} más[/dim]"

        console.print(Panel(
            f"[bold yellow]⚠️  REACTIVAR TODAS LAS VARIANTES SIN STOCK[/bold yellow]\n\n"
            f"[bold]Producto:[/bold] {title}\n"
            f"[bold]Variantes a reactivar:[/bold] {len(paused_variations)}\n\n"
            + preview_lines,
            border_style="yellow",
            box=box.DOUBLE
        ))

        stock_str = Prompt.ask(
            f"\n¿Cuántas unidades de stock para CADA una de las {len(paused_variations)} variantes?"
        )
        try:
            new_stock = int(stock_str)
        except ValueError:
            console.print("[red]❌ Valor inválido[/red]")
            return

        if new_stock <= 0:
            console.print("[red]❌ El stock debe ser mayor a 0[/red]")
            return

        confirmation = Prompt.ask(
            f"\nEscribí 'SI' para reactivar {len(paused_variations)} variantes "
            f"con {new_stock} unidades c/u",
            default="NO"
        )
        if confirmation.upper() != 'SI':
            console.print("[yellow]⚠️  Operación cancelada[/yellow]")
            return

        console.print("\n[cyan]⏳ Actualizando en MercadoLibre...[/cyan]")

        paused_ids = {v.get('id') for v in paused_variations}
        updated = [
            {"id": v['id'], "available_quantity": new_stock if v['id'] in paused_ids
             else v.get('available_quantity', 0)}
            for v in all_variations
        ]

        try:
            self.api._make_request('PUT', f"/items/{item_id}", json={"variations": updated})
            console.print(Panel(
                f"[bold green]✓ {len(paused_variations)} variantes reactivadas exitosamente[/bold green]\n"
                f"[dim]Stock asignado: {new_stock} unidades por variante[/dim]",
                border_style="green",
                box=box.ROUNDED
            ))
        except Exception as e:
            console.print(f"[red]❌ Error al reactivar variantes: {e}[/red]")

    # ── Loop principal ────────────────────────────────────────────────────────

    def run(self):
        verificar_cache_al_inicio(self.db, self.api, self.user_id)

        while True:
            show_header("REACTIVAR VARIANTES - MERCADOLIBRE", self.db)
            choice = self.show_menu()

            if choice == "1":
                self.listar_productos_con_variantes()
            elif choice == "2":
                self.buscar_por_id()
            elif choice == "3":
                self.buscar_por_titulo()
            elif choice == "4":
                sincronizar_productos(self.api, self.db, self.user_id)
            elif choice == "5":
                console.print("\n[bold cyan]¡Hasta luego![/bold cyan]")
                sys.exit(0)

            console.print("\n")
            Prompt.ask("Presioná Enter para continuar")


def main():
    try:
        activator = VariantActivator()
        activator.run()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]⚠️  Programa interrumpido[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]❌ Error inesperado: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
