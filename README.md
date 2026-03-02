# ml-scripts — Toolbox de MercadoLibre

Scripts CLI para gestión de productos en MercadoLibre.

## Estructura

```
ml-scripts/
├── lib/                  # Librería compartida
│   ├── ml_auth.py       # Autenticación OAuth2
│   ├── ml_api.py        # Cliente API + sync + UI
│   └── ml_db.py         # Base de datos SQLite
├── scripts/
│   ├── ml_delete_product.py
│   ├── ml_pause_product.py
│   └── ml_update_price.py
├── config/               # Credenciales (excluidas del repo)
└── data/                 # Base de datos local (excluida del repo)
```

## Uso

```bash
cd ~/Proyectos/ml-scripts
source venv/bin/activate

# Borrar productos
python scripts/ml_delete_product.py

# Pausar/activar productos
python scripts/ml_pause_product.py

# Actualizar precios
python scripts/ml_update_price.py
```

## Credenciales

Las credenciales OAuth2 deben estar en `config/ml_credentials_palishopping.json`.
Para renovarlas, usar el script `renovar_credenciales.sh` del proyecto Analisis_ML.
