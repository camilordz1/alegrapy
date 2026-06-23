from alegra import AlegraClient, session, users, estimates, bank_accounts
from decouple import config

if __name__ == '__main__':
    
    # Configurar las credenciales desde el archivo .env o variables de entorno
    user = config("ALEGRA_USER", default="tu_usuario@alegra.com")
    token = config("TOKEN", default="tu_token_api")

    print("--- Probando con el nuevo AlegraClient (Recomendado) ---")
    client = AlegraClient(user=user, token=token)

    # 1. Consultar el usuario autenticado
    try:
        my_user = client.users.self_info()
        print("Usuario Autenticado:", my_user.get("email"), "-", my_user.get("name"))
    except Exception as e:
        print("Error al obtener usuario:", e)

    # 2. Listar cotizaciones (utilizando los nuevos valores por defecto: start=0, limit=30)
    try:
        print("\nListando cotizaciones...")
        cotizaciones = client.estimates.list(limit=3)
        print("Cotizaciones obtenidas:", len(cotizaciones))
    except Exception as e:
        print("Error al obtener cotizaciones:", e)

    # 3. Listar cuentas bancarias
    try:
        print("\nListando cuentas bancarias...")
        cuentas = client.bank_accounts.list(limit=5)
        for c in cuentas:
            print(f"- Cuenta ID {c.get('id')}: {c.get('name')} (Saldo: {c.get('balance')})")
    except Exception as e:
        print("Error al obtener cuentas bancarias:", e)

    print("\n--- Probando con el estilo heredado (Compatibilidad) ---")
    session.user = user
    session.token = token

    # 4. Listar facturas (utilizando los nuevos valores por defecto: start=0, limit=30)
    try:
        print("\nListando facturas...")
        facturas = client.invoices.list(limit=3, start=10)
        print("Facturas obtenidas:", len(facturas))
    except Exception as e:
        print("Error al obtener facturas:", e) 

    try:
        # Se puede instanciar el recurso heredado directamente en minúsculas
        u_legacy = users()
        print("Usuario Autenticado (Legacy):", u_legacy.self_info().get("email"))
    except Exception as e:
        print("Error en modo legacy:", e)

