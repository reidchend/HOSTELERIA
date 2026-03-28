# database/migrations/add_telegram_message_id.py
"""
Migración para agregar columna telegram_message_id a la tabla bitacora.

Ejecutar con:
    python -m database.migrations.add_telegram_message_id
"""


def ejecutar():
    import sqlite3
    import os

    url = os.getenv("DATABASE_URL", "sqlite:///hotel.db")
    db_path = url[len("sqlite:///") :] if url.startswith("sqlite:///") else "hotel.db"
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.getcwd(), db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Verificar si la columna ya existe
    cursor.execute("PRAGMA table_info(bitacora)")
    columnas = [col[1] for col in cursor.fetchall()]

    if "telegram_message_id" not in columnas:
        cursor.execute("""
            ALTER TABLE bitacora ADD COLUMN telegram_message_id VARCHAR(50)
        """)
        conn.commit()
        print("✅ Columna telegram_message_id agregada a bitacora")
    else:
        print("ℹ️  Columna telegram_message_id ya existe en bitacora")

    conn.close()


if __name__ == "__main__":
    ejecutar()
