"""
Manejo de base de datos SQLite para cache de productos
"""
import json
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List


def _normalizar(texto: str) -> str:
    """Quita acentos y pasa a minúsculas para comparación sin tildes"""
    if not texto:
        return ""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.lower()


class ProductDatabase:
    """Maneja el registro de operaciones y cache en SQLite"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._create_tables()

    def _create_tables(self):
        """Crea las tablas necesarias si no existen"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Tabla de productos borrados (ya existía)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deleted_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                title TEXT,
                price REAL,
                status TEXT,
                deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER
            )
        ''')

        # Tabla de cache de productos
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                price REAL,
                available_quantity INTEGER,
                sold_quantity INTEGER,
                status TEXT,
                thumbnail TEXT,
                permalink TEXT,
                category_id TEXT,
                listing_type_id TEXT,
                condition TEXT,
                ml_data TEXT,
                last_sync TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Índices para búsquedas rápidas
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_title ON products(title)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_price ON products(price)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_status ON products(status)')

        # Tabla de metadata
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def save_deleted_product(self, item_id: str, title: str, price: float,
                            status: str, user_id: int):
        """Guarda un producto borrado en la base de datos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO deleted_products (item_id, title, price, status, user_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (item_id, title, price, status, user_id))

        conn.commit()
        conn.close()

    def get_deleted_history(self, limit: int = 50) -> List[Dict]:
        """Obtiene el historial de productos borrados"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT item_id, title, price, deleted_at, user_id
            FROM deleted_products
            ORDER BY deleted_at DESC
            LIMIT ?
        ''', (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'item_id': row[0],
                'title': row[1],
                'price': row[2],
                'deleted_at': row[3],
                'user_id': row[4]
            }
            for row in rows
        ]

    # ==================== MÉTODOS DE CACHE ====================

    def upsert_product(self, product_data: Dict):
        """Inserta o actualiza un producto en el cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO products (
                item_id, title, price, available_quantity, sold_quantity,
                status, thumbnail, permalink, category_id, listing_type_id,
                condition, ml_data, last_sync
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                title = excluded.title,
                price = excluded.price,
                available_quantity = excluded.available_quantity,
                sold_quantity = excluded.sold_quantity,
                status = excluded.status,
                thumbnail = excluded.thumbnail,
                permalink = excluded.permalink,
                category_id = excluded.category_id,
                listing_type_id = excluded.listing_type_id,
                condition = excluded.condition,
                ml_data = excluded.ml_data,
                last_sync = excluded.last_sync
        ''', (
            product_data.get('id'),
            product_data.get('title'),
            product_data.get('price'),
            product_data.get('available_quantity'),
            product_data.get('sold_quantity'),
            product_data.get('status'),
            product_data.get('thumbnail'),
            product_data.get('permalink'),
            product_data.get('category_id'),
            product_data.get('listing_type_id'),
            product_data.get('condition'),
            json.dumps(product_data),
            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def bulk_upsert_products(self, products: List[Dict]):
        """Inserta o actualiza múltiples productos (más eficiente)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('BEGIN TRANSACTION')

        for product_data in products:
            cursor.execute('''
                INSERT INTO products (
                    item_id, title, price, available_quantity, sold_quantity,
                    status, thumbnail, permalink, category_id, listing_type_id,
                    condition, ml_data, last_sync
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    title = excluded.title,
                    price = excluded.price,
                    available_quantity = excluded.available_quantity,
                    sold_quantity = excluded.sold_quantity,
                    status = excluded.status,
                    thumbnail = excluded.thumbnail,
                    permalink = excluded.permalink,
                    category_id = excluded.category_id,
                    listing_type_id = excluded.listing_type_id,
                    condition = excluded.condition,
                    ml_data = excluded.ml_data,
                    last_sync = excluded.last_sync
            ''', (
                product_data.get('id'),
                product_data.get('title'),
                product_data.get('price'),
                product_data.get('available_quantity'),
                product_data.get('sold_quantity'),
                product_data.get('status'),
                product_data.get('thumbnail'),
                product_data.get('permalink'),
                product_data.get('category_id'),
                product_data.get('listing_type_id'),
                product_data.get('condition'),
                json.dumps(product_data),
                datetime.now().isoformat()
            ))

        conn.commit()
        conn.close()

    def get_all_cached_products(self, status: str = None, order_by: str = 'title') -> List[Dict]:
        """Obtiene todos los productos del cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        valid_order_columns = ['title', 'price', 'available_quantity', 'sold_quantity']
        if order_by not in valid_order_columns:
            order_by = 'title'

        query = f'''
            SELECT item_id, title, price, available_quantity, sold_quantity, status,
                   thumbnail, permalink, condition, last_sync
            FROM products
        '''

        if status:
            query += f" WHERE status = '{status}'"

        query += f" ORDER BY {order_by}"

        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'id': row[0],
                'title': row[1],
                'price': row[2],
                'available_quantity': row[3],
                'sold_quantity': row[4],
                'status': row[5],
                'thumbnail': row[6],
                'permalink': row[7],
                'condition': row[8],
                'last_sync': row[9]
            }
            for row in rows
        ]

    def search_products_by_title(self, keywords: List[str], status: str = 'active') -> List[Dict]:
        """Busca productos por palabra(s) clave en el título, ignorando acentos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT item_id, title, price, available_quantity, sold_quantity, status
            FROM products
            WHERE status = ?
            ORDER BY title
        ''', (status,))
        rows = cursor.fetchall()
        conn.close()

        # Filtrar en Python con comparación normalizada (ignora acentos)
        normalized_keywords = [_normalizar(kw) for kw in keywords]

        return [
            {
                'id': row[0],
                'title': row[1],
                'price': row[2],
                'available_quantity': row[3],
                'sold_quantity': row[4],
                'status': row[5]
            }
            for row in rows
            if all(kw in _normalizar(row[1] or '') for kw in normalized_keywords)
        ]

    def get_product_by_id(self, item_id: str) -> Optional[Dict]:
        """Obtiene un producto del cache por su ID"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT item_id, title, price, available_quantity, sold_quantity,
                   status, thumbnail, permalink, condition, ml_data
            FROM products
            WHERE item_id = ?
        ''', (item_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'id': row[0],
                'title': row[1],
                'price': row[2],
                'available_quantity': row[3],
                'sold_quantity': row[4],
                'status': row[5],
                'thumbnail': row[6],
                'permalink': row[7],
                'condition': row[8],
                'ml_data': json.loads(row[9]) if row[9] else {}
            }
        return None

    def update_product_status(self, item_id: str, status: str):
        """Actualiza el status de un producto en el cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE products
            SET status = ?, last_sync = ?
            WHERE item_id = ?
        ''', (status, datetime.now().isoformat(), item_id))

        conn.commit()
        conn.close()

    def update_product_price(self, item_id: str, new_price: float):
        """Actualiza el precio de un producto en el cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE products
            SET price = ?, last_sync = ?
            WHERE item_id = ?
        ''', (new_price, datetime.now().isoformat(), item_id))

        conn.commit()
        conn.close()

    def get_cached_item_ids(self) -> set:
        """Obtiene todos los IDs de productos en cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT item_id FROM products')
        rows = cursor.fetchall()
        conn.close()

        return set(row[0] for row in rows)

    def get_cache_stats(self) -> Dict:
        """Obtiene estadísticas del cache"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM products')
        total = cursor.fetchone()[0]

        cursor.execute('''
            SELECT status, COUNT(*)
            FROM products
            GROUP BY status
        ''')
        by_status = dict(cursor.fetchall())

        cursor.execute('SELECT SUM(available_quantity) FROM products WHERE status = "active"')
        total_stock = cursor.fetchone()[0] or 0

        cursor.execute('''
            SELECT SUM(price * available_quantity)
            FROM products
            WHERE status = "active"
        ''')
        total_value = cursor.fetchone()[0] or 0

        conn.close()

        return {
            'total': total,
            'by_status': by_status,
            'total_stock': int(total_stock),
            'total_value': float(total_value)
        }

    def get_last_sync(self) -> Optional[datetime]:
        """Obtiene la fecha de la última sincronización"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT value FROM sync_metadata
            WHERE key = 'last_sync'
        ''')

        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            try:
                return datetime.fromisoformat(row[0])
            except:
                return None
        return None

    def update_last_sync(self):
        """Actualiza el timestamp de última sincronización"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO sync_metadata (key, value, updated_at)
            VALUES ('last_sync', ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        ''', (datetime.now().isoformat(), datetime.now().isoformat()))

        conn.commit()
        conn.close()
