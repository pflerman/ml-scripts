"""
Manejo de credenciales OAuth2 para MercadoLibre
"""
import json
import time
import sys
from pathlib import Path

import requests
from rich.console import Console

console = Console()

API_BASE_URL = "https://api.mercadolibre.com"


class MLAuth:
    """Maneja la autenticación OAuth2 con MercadoLibre"""

    def __init__(self, credentials_path: Path):
        self.credentials_path = credentials_path
        self.credentials = self._load_credentials()
        self._check_token_expiration()

    def _load_credentials(self) -> dict:
        """Carga las credenciales desde el archivo JSON"""
        try:
            with open(self.credentials_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            console.print(f"[red]❌ Error: No se encontró el archivo de credenciales en {self.credentials_path}[/red]")
            sys.exit(1)
        except json.JSONDecodeError:
            console.print("[red]❌ Error: El archivo de credenciales tiene formato inválido[/red]")
            sys.exit(1)

    def _save_credentials(self):
        """Guarda las credenciales actualizadas"""
        with open(self.credentials_path, 'w') as f:
            json.dump(self.credentials, f)

    def _check_token_expiration(self):
        """Verifica si el token expiró y lo renueva si es necesario"""
        timestamp = self.credentials.get('timestamp', 0)
        expires_in = self.credentials.get('expires_in', 21600)

        if time.time() - timestamp >= (expires_in - 300):
            console.print("[yellow]⚠️  Token expirado, renovando...[/yellow]")
            self._refresh_token()

    def _refresh_token(self):
        """Renueva el access token usando el refresh token"""
        url = f"{API_BASE_URL}/oauth/token"
        data = {
            'grant_type': 'refresh_token',
            'client_id': self.credentials['app_id'],
            'client_secret': self.credentials['client_secret'],
            'refresh_token': self.credentials['refresh_token']
        }

        try:
            response = requests.post(url, data=data)
            response.raise_for_status()

            new_credentials = response.json()
            self.credentials['access_token'] = new_credentials['access_token']
            self.credentials['refresh_token'] = new_credentials['refresh_token']
            self.credentials['timestamp'] = time.time()
            self.credentials['expires_in'] = new_credentials.get('expires_in', 21600)

            self._save_credentials()
            console.print("[green]✓ Token renovado exitosamente[/green]")
        except requests.exceptions.RequestException as e:
            console.print(f"[red]❌ Error al renovar token: {e}[/red]")
            sys.exit(1)
